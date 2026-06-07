"""Forge Sentinel — schedule CRUD and run history API."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user
from backend.core.sentinel import calculate_next_run
from backend.core.trail import log_action
from backend.database import get_db
from backend.models.schedule import Schedule
from backend.models.sentinel_run import SentinelRun
from backend.models.user import User
from backend.utils.datetime_utils import utc_iso

router = APIRouter(prefix="/schedules", tags=["sentinel"])


def _utc_iso(dt: datetime | None) -> str | None:
    """Backward-compat alias — delegates to the shared utility."""
    return utc_iso(dt)


# Schemas
class ScheduleCreate(BaseModel):
    name: str
    mission_id: int
    target_ids: list[int]
    frequency: str = "daily"
    day_of_week: int | None = None
    day_of_month: int | None = None
    time_of_day: str = "02:00"
    custom_interval_hours: int | None = None
    timezone: str = "UTC"
    notify_on_regression: bool = True
    notify_on_critical: bool = True
    regression_threshold: float = 5.0
    alert_channels: list[str] = ["in_app"]
    alert_emails: str | None = None
    slack_webhook_url: str | None = None
    auto_generate_report: bool = False
    report_format: str = "pdf"


class ScheduleUpdate(BaseModel):
    name: str | None = None
    target_ids: list[int] | None = None
    frequency: str | None = None
    day_of_week: int | None = None
    day_of_month: int | None = None
    time_of_day: str | None = None
    custom_interval_hours: int | None = None
    enabled: bool | None = None
    notify_on_regression: bool | None = None
    notify_on_critical: bool | None = None
    regression_threshold: float | None = None
    alert_channels: list[str] | None = None
    alert_emails: str | None = None
    slack_webhook_url: str | None = None
    auto_generate_report: bool | None = None
    report_format: str | None = None


def _schedule_to_dict(s: Schedule) -> dict:
    # Get compliance delta from latest completed run
    compliance_delta = None
    from sqlalchemy.orm import object_session
    session = object_session(s)
    if session:
        latest_run = (
            session.query(SentinelRun)
            .filter(SentinelRun.schedule_id == s.id, SentinelRun.status == "completed")
            .order_by(SentinelRun.started_at.desc())
            .first()
        )
        if latest_run and latest_run.compliance_delta is not None:
            compliance_delta = latest_run.compliance_delta

    return {
        "id": s.id,
        "name": s.name,
        "mission_id": s.mission_id,
        "target_ids": json.loads(s.target_ids_json or "[]"),
        "frequency": s.frequency,
        "day_of_week": s.day_of_week,
        "day_of_month": s.day_of_month,
        "time_of_day": s.time_of_day,
        "custom_interval_hours": s.custom_interval_hours,
        "timezone": s.timezone,
        "enabled": s.enabled,
        "last_run_at": _utc_iso(s.last_run_at),
        "last_run_status": s.last_run_status,
        "last_compliance": s.last_compliance,
        "compliance_delta": compliance_delta,
        "next_run_at": _utc_iso(s.next_run_at),
        "notify_on_regression": s.notify_on_regression,
        "notify_on_critical": s.notify_on_critical,
        "regression_threshold": s.regression_threshold,
        "alert_channels": json.loads(s.alert_channels_json or '["in_app"]'),
        "alert_emails": s.alert_emails,
        "slack_webhook_url": s.slack_webhook_url,
        "auto_generate_report": s.auto_generate_report,
        "report_format": s.report_format,
        "created_at": _utc_iso(s.created_at),
    }


def _run_to_dict(r: SentinelRun) -> dict:
    return {
        "id": r.id,
        "schedule_id": r.schedule_id,
        "scan_ids": json.loads(r.scan_ids_json or "[]"),
        "previous_scan_ids": json.loads(r.previous_scan_ids_json or "[]") if r.previous_scan_ids_json else [],
        "status": r.status,
        "compliance_current": r.compliance_current,
        "compliance_previous": r.compliance_previous,
        "compliance_delta": r.compliance_delta,
        "rules_regressed": r.rules_regressed,
        "rules_improved": r.rules_improved,
        "critical_openings": r.critical_openings,
        "comparison_details": json.loads(r.comparison_details_json) if r.comparison_details_json else None,
        "alerts_sent": json.loads(r.alerts_sent_json or "[]") if r.alerts_sent_json else [],
        "started_at": _utc_iso(r.started_at),
        "completed_at": _utc_iso(r.completed_at),
    }


# Endpoints
@router.get("")
def list_schedules(
    mission_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Schedule)
    if mission_id is not None:
        q = q.filter(Schedule.mission_id == mission_id)
    schedules = q.order_by(Schedule.created_at.desc()).all()
    return {"data": [_schedule_to_dict(s) for s in schedules]}


# Report download (MUST be before /{schedule_id} to avoid route conflict)

@router.get("/reports/{filename}")
async def download_sentinel_report(filename: str, _=Depends(get_current_user)):
    """Download a Sentinel-generated report file."""
    import re
    from pathlib import Path
    from fastapi.responses import FileResponse
    from backend.config import PROJECT_ROOT

    # Sanitize filename — only allow alphanumeric, dash, underscore, dot
    if not re.match(r"^[\w\-]+\.(pdf|xlsx|csv)$", filename, re.ASCII):
        raise HTTPException(status_code=400, detail="Invalid filename")

    report_dir = PROJECT_ROOT / "data" / "sentinel_reports"
    file_path = report_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    media_types = {
        ".pdf": "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "text/csv",
    }
    media_type = media_types.get(file_path.suffix, "application/octet-stream")
    return FileResponse(file_path, filename=filename, media_type=media_type)


@router.post("")
def create_schedule(
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = Schedule(
        name=payload.name,
        mission_id=payload.mission_id,
        target_ids_json=json.dumps(payload.target_ids),
        frequency=payload.frequency,
        day_of_week=payload.day_of_week,
        day_of_month=payload.day_of_month,
        time_of_day=payload.time_of_day,
        custom_interval_hours=payload.custom_interval_hours,
        timezone=payload.timezone,
        notify_on_regression=payload.notify_on_regression,
        notify_on_critical=payload.notify_on_critical,
        regression_threshold=payload.regression_threshold,
        alert_channels_json=json.dumps(payload.alert_channels),
        alert_emails=payload.alert_emails,
        slack_webhook_url=payload.slack_webhook_url,
        auto_generate_report=payload.auto_generate_report,
        report_format=payload.report_format,
        created_by=current_user.id,
    )
    s.next_run_at = calculate_next_run(s)
    db.add(s)
    db.commit()
    db.refresh(s)
    log_action(db, user=current_user, mission_id=payload.mission_id, action="schedule_created", entity_type="schedule", entity_id=s.id, entity_label=s.name)
    db.commit()
    return {"data": _schedule_to_dict(s)}


@router.get("/{schedule_id}")
def get_schedule(schedule_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"data": _schedule_to_dict(s)}


@router.put("/{schedule_id}")
def update_schedule(
    schedule_id: int,
    payload: ScheduleUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")

    update_data = payload.dict(exclude_unset=True)
    if "target_ids" in update_data:
        s.target_ids_json = json.dumps(update_data.pop("target_ids"))
    if "alert_channels" in update_data:
        s.alert_channels_json = json.dumps(update_data.pop("alert_channels"))
    for key, val in update_data.items():
        setattr(s, key, val)

    s.next_run_at = calculate_next_run(s)
    s.updated_at = datetime.now(timezone.utc)
    log_action(db, mission_id=s.mission_id, action="schedule_updated", entity_type="schedule", entity_id=schedule_id, entity_label=s.name)
    db.commit()
    db.refresh(s)
    return {"data": _schedule_to_dict(s)}


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    schedule_name = s.name
    mission_id = s.mission_id
    db.delete(s)
    log_action(db, mission_id=mission_id, action="schedule_deleted", entity_type="schedule", entity_id=schedule_id, entity_label=schedule_name)
    db.commit()
    return {"message": "Schedule deleted"}


@router.post("/{schedule_id}/toggle")
def toggle_schedule(schedule_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    s.enabled = not s.enabled
    if s.enabled:
        s.next_run_at = calculate_next_run(s)
    log_action(db, mission_id=s.mission_id, action="schedule_toggled", entity_type="schedule", entity_id=schedule_id, entity_label=s.name, details={"enabled": s.enabled})
    db.commit()
    return {"data": _schedule_to_dict(s)}


@router.post("/{schedule_id}/run-now")
async def run_now(schedule_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")

    import asyncio
    import logging
    from backend.core.sentinel import execute_scheduled_run
    from backend.database import SessionLocal

    _logger = logging.getLogger("auditforge.sentinel")

    async def _run_with_logging():
        try:
            await execute_scheduled_run(SessionLocal, schedule_id)
        except Exception as exc:
            _logger.error("run-now task for schedule %d crashed: %s", schedule_id, exc, exc_info=True)

    asyncio.create_task(_run_with_logging())
    log_action(db, mission_id=s.mission_id, action="schedule_run_now", entity_type="schedule", entity_id=schedule_id, entity_label=s.name)
    db.commit()
    return {"message": "Run triggered", "schedule_id": schedule_id}


@router.get("/{schedule_id}/runs")
def get_schedule_runs(
    schedule_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = (
        db.query(SentinelRun)
        .filter(SentinelRun.schedule_id == schedule_id)
        .order_by(SentinelRun.started_at.desc())
    )
    total = q.count()
    runs = q.offset(skip).limit(limit).all()
    return {"total": total, "data": [_run_to_dict(r) for r in runs]}


@router.get("/{schedule_id}/runs/{run_id}")
def get_run_detail(
    schedule_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    r = (
        db.query(SentinelRun)
        .filter(SentinelRun.id == run_id, SentinelRun.schedule_id == schedule_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")
    result = _run_to_dict(r)
    if r.comparison_details_json:
        result["comparison"] = json.loads(r.comparison_details_json)
    return {"data": result}


@router.post("/{schedule_id}/test-alerts")
async def test_alerts(schedule_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Send a test alert to all configured channels."""
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")

    from backend.core.alert_dispatcher import dispatch_alerts

    test_alerts = [{
        "title": "Test Alert — Forge Sentinel",
        "body": f"This is a test alert from schedule '{s.name}'. If you see this, alerts are working!",
        "type": "info",
        "icon": "check-circle",
    }]
    sent = await dispatch_alerts(db, schedule=s, run=None, alerts=test_alerts)
    db.commit()
    return {"sent": sent, "channels_configured": json.loads(s.alert_channels_json or "[]")}
