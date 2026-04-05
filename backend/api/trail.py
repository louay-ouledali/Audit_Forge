"""Forge Trail — mission-scoped activity log API."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user
from backend.database import get_db
from backend.models.audit_log import AuditLog
from backend.models.mission import Mission
from backend.models.user import User
from backend.utils.datetime_utils import utc_iso

router = APIRouter(prefix="/trail", tags=["trail"])


def _apply_filters(q, mission_id: int, action: str | None, username: str | None,
                   date_from: str | None, date_to: str | None):
    """Apply optional filters to an AuditLog query."""
    q = q.filter(AuditLog.mission_id == mission_id)
    if action:
        q = q.filter(AuditLog.action == action)
    if username:
        q = q.filter(AuditLog.username.ilike(f"%{username}%"))
    if date_from:
        try:
            dt = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            q = q.filter(AuditLog.created_at >= dt.replace(tzinfo=None))
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            q = q.filter(AuditLog.created_at <= dt.replace(tzinfo=None))
        except ValueError:
            pass
    return q


def _verify_mission(db: Session, mission_id: int) -> None:
    """Raise 404 if mission does not exist."""
    if not db.query(Mission.id).filter(Mission.id == mission_id).first():
        raise HTTPException(status_code=404, detail="Mission not found")


@router.get("/{mission_id}")
def get_mission_activity(
    mission_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    action: str | None = Query(None),
    username: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Paginated activity log for a mission (newest first)."""
    _verify_mission(db, mission_id)
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    q = _apply_filters(q, mission_id, action, username, date_from, date_to)
    total = q.count()
    items = q.offset(skip).limit(limit).all()
    return {
        "total": total,
        "data": [
            {
                "id": e.id,
                "username": e.username,
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "entity_label": e.entity_label,
                "details_json": e.details_json,
                "details": json.loads(e.details_json) if e.details_json else None,
                "created_at": utc_iso(e.created_at),
            }
            for e in items
        ],
    }


@router.get("/{mission_id}/recent")
def get_recent_activity(
    mission_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Last 15 actions for the MissionOverview activity feed."""
    _verify_mission(db, mission_id)
    items = (
        db.query(AuditLog)
        .filter(AuditLog.mission_id == mission_id)
        .order_by(AuditLog.created_at.desc())
        .limit(15)
        .all()
    )
    return {
        "data": [
            {
                "id": e.id,
                "username": e.username,
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "entity_label": e.entity_label,
                "details": json.loads(e.details_json) if e.details_json else None,
                "created_at": utc_iso(e.created_at),
            }
            for e in items
        ],
    }


@router.get("/{mission_id}/export")
def export_mission_activity(
    mission_id: int,
    format: str = Query("csv", regex="^(csv|json)$"),
    action: str | None = Query(None),
    username: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Export full mission activity log as CSV or JSON download."""
    _verify_mission(db, mission_id)
    q = db.query(AuditLog).order_by(AuditLog.created_at.asc())
    q = _apply_filters(q, mission_id, action, username, date_from, date_to)
    items = q.all()

    filename = f"audit_trail_mission_{mission_id}"

    if format == "json":
        rows = [
            {
                "timestamp": utc_iso(e.created_at),
                "username": e.username,
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "entity_label": e.entity_label,
                "details": json.loads(e.details_json) if e.details_json else None,
                "ip_address": getattr(e, "ip_address", None),
            }
            for e in items
        ]
        content = json.dumps(rows, indent=2, ensure_ascii=False)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )

    # CSV format
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Timestamp", "Username", "Action", "Entity Type", "Entity ID", "Entity Label", "Details", "IP Address"])
    for e in items:
        writer.writerow([
            utc_iso(e.created_at),
            e.username,
            e.action,
            e.entity_type or "",
            e.entity_id or "",
            e.entity_label or "",
            e.details_json or "",
            getattr(e, "ip_address", "") or "",
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
