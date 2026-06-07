"""Forge Resolve — REST API for remediation workflows."""
from __future__ import annotations

import json
import logging
import threading
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user, verify_password
from backend.core.trail import log_action
from backend.database import get_db
from backend.models.remediation_item import RemediationItem
from backend.models.remediation_session import RemediationSession
from backend.models.scan import Scan
from backend.models.target import Target
from backend.schemas.resolve import (
    AgentExecuteRequest,
    BulkSelectRequest,
    ExecuteRequest,
    ResolveItemResponse,
    ResolveItemUpdate,
    ResolveSessionCreate,
    ResolveSessionResponse,
    ResolveSessionSummary,
    ScanIntelligenceRequest,
    ScanIntelligenceResponse,
)

logger = logging.getLogger("auditforge.resolve")

router = APIRouter(prefix="/resolve", tags=["resolve"])


# 1. Create session

@router.post("/sessions", response_model=ResolveSessionResponse)
def create_resolve_session(
    body: ResolveSessionCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a remediation session from completed scan(s) for a target."""
    # Validate target
    target = db.query(Target).filter(Target.id == body.target_id).first()
    if not target:
        raise HTTPException(404, "Target not found")

    # Validate scans
    scans = (
        db.query(Scan)
        .filter(
            Scan.id.in_(body.scan_ids),
            Scan.target_id == body.target_id,
            Scan.status.in_(["completed", "imported"]),
        )
        .all()
    )
    if not scans:
        raise HTTPException(400, "No completed scans found for this target with the given IDs")

    # Build items from FAIL findings
    from backend.core.resolve_engine import build_remediation_items

    items_data = build_remediation_items(body.scan_ids, body.target_id, db)

    if not items_data:
        raise HTTPException(400, "No FAIL findings found across the selected scans")

    # Create session
    session = RemediationSession(
        mission_id=body.mission_id,
        target_id=body.target_id,
        created_by=getattr(current_user, "username", "system"),
        status="draft",
        total_items=len(items_data),
        scan_ids_json=json.dumps(body.scan_ids),
    )
    db.add(session)
    db.flush()

    # Create items
    for item_data in items_data:
        item = RemediationItem(session_id=session.id, **item_data)
        db.add(item)

    log_action(
        db, user=current_user, mission_id=body.mission_id,
        action="resolve_session_created",
        entity_type="remediation_session", entity_id=session.id,
        entity_label=target.hostname or target.ip_address,
        details={"scan_ids": body.scan_ids, "total_items": len(items_data)},
    )
    db.commit()
    db.refresh(session)

    return session


# 2. Get session

@router.get("/sessions/{session_id}", response_model=ResolveSessionResponse)
def get_resolve_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session = db.query(RemediationSession).filter(RemediationSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    return session


# 3. List sessions for target

@router.get("/targets/{target_id}/sessions", response_model=list[ResolveSessionSummary])
def list_target_sessions(
    target_id: int,
    mission_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    sessions = (
        db.query(RemediationSession)
        .filter(
            RemediationSession.target_id == target_id,
            RemediationSession.mission_id == mission_id,
        )
        .order_by(RemediationSession.created_at.desc())
        .all()
    )
    return sessions


# 4. Update single item

@router.put("/items/{item_id}", response_model=ResolveItemResponse)
def update_resolve_item(
    item_id: int,
    body: ResolveItemUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = db.query(RemediationItem).filter(RemediationItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "Item not found")

    session = db.query(RemediationSession).filter(RemediationSession.id == item.session_id).first()
    if session and session.status not in ("draft", "exported"):
        raise HTTPException(409, "Cannot modify items in a session that is executing or completed")

    if body.selected is not None:
        item.selected = body.selected
    if body.remediation_command is not None:
        item.remediation_command = body.remediation_command
        item.command_source = "auditor_edit"
    if body.order_index is not None:
        item.order_index = body.order_index

    log_action(
        db, user=current_user,
        mission_id=session.mission_id if session else None,
        action="resolve_item_updated",
        entity_type="remediation_item", entity_id=item.id,
        entity_label=item.section_number,
    )
    db.commit()
    db.refresh(item)
    return item


# 5. Bulk select/deselect

@router.put("/sessions/{session_id}/bulk-select")
def bulk_select_items(
    session_id: int,
    body: BulkSelectRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session = db.query(RemediationSession).filter(RemediationSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    updated = (
        db.query(RemediationItem)
        .filter(
            RemediationItem.session_id == session_id,
            RemediationItem.id.in_(body.item_ids),
        )
        .update({"selected": body.selected}, synchronize_session="fetch")
    )

    log_action(
        db, user=current_user, mission_id=session.mission_id,
        action="resolve_bulk_select",
        entity_type="remediation_session", entity_id=session_id,
        details={"count": updated, "selected": body.selected},
    )
    db.commit()

    return {"updated": updated}


# 6. Export script (air-gapped)

@router.post("/sessions/{session_id}/export")
def export_resolve_script(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session = db.query(RemediationSession).filter(RemediationSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    target = db.query(Target).filter(Target.id == session.target_id).first()
    if not target:
        raise HTTPException(404, "Target not found")

    items = (
        db.query(RemediationItem)
        .filter(RemediationItem.session_id == session_id)
        .order_by(RemediationItem.order_index)
        .all()
    )

    from backend.core.resolve_engine import generate_remediation_script

    try:
        zip_bytes, zip_filename = generate_remediation_script(session, items, target, db)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    session.status = "exported"
    session.execution_mode = "airgap"

    log_action(
        db, user=current_user, mission_id=session.mission_id,
        action="resolve_script_exported",
        entity_type="remediation_session", entity_id=session_id,
        entity_label=target.hostname or target.ip_address,
        details={"filename": zip_filename},
    )
    db.commit()

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


# 7. Execute network (live)

@router.post("/sessions/{session_id}/execute")
def execute_resolve_network(
    session_id: int,
    body: ExecuteRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session = db.query(RemediationSession).filter(RemediationSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    # Password gate for remediation execution
    if not body.current_password or not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(403, "Password required for remediation execution")

    if session.status in ("executing",):
        raise HTTPException(409, "Session is already executing")

    # Check privilege warnings
    privileged_items = (
        db.query(RemediationItem)
        .filter(
            RemediationItem.session_id == session_id,
            RemediationItem.selected == True,
            RemediationItem.requires_privilege == True,
        )
        .all()
    )

    if privileged_items and not body.confirm_privilege:
        return {
            "warning": "privilege_required",
            "message": f"{len(privileged_items)} commands require elevated privileges",
            "privileged_commands": [
                {
                    "id": i.id,
                    "section": i.section_number,
                    "title": i.rule_title,
                    "command": i.remediation_command,
                }
                for i in privileged_items
            ],
        }

    log_action(
        db, user=current_user, mission_id=session.mission_id,
        action="resolve_executed_network",
        entity_type="remediation_session", entity_id=session_id,
        entity_label=f"Session #{session_id}",
    )
    db.commit()

    # Run in background thread
    from backend.core.resolve_engine import execute_remediation_network
    from backend.database import SessionLocal

    def _run():
        _db = SessionLocal()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(execute_remediation_network(session_id, _db, user=current_user))
            loop.close()
        except Exception as exc:
            logger.error("Background remediation failed: %s", exc)
        finally:
            _db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {"status": "executing", "session_id": session_id}


# 8. Execute via agent

@router.post("/sessions/{session_id}/execute-agent")
def execute_resolve_agent(
    session_id: int,
    body: AgentExecuteRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session = db.query(RemediationSession).filter(RemediationSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    if session.status in ("executing",):
        raise HTTPException(409, "Session is already executing")

    # Check privilege warnings
    privileged_items = (
        db.query(RemediationItem)
        .filter(
            RemediationItem.session_id == session_id,
            RemediationItem.selected == True,
            RemediationItem.requires_privilege == True,
        )
        .all()
    )

    if privileged_items and not body.confirm_privilege:
        return {
            "warning": "privilege_required",
            "message": f"{len(privileged_items)} commands require elevated privileges",
            "privileged_commands": [
                {"id": i.id, "section": i.section_number, "command": i.remediation_command}
                for i in privileged_items
            ],
        }

    log_action(
        db, user=current_user, mission_id=session.mission_id,
        action="resolve_executed_agent",
        entity_type="remediation_session", entity_id=session_id,
    )
    db.commit()

    # Run in background thread
    from backend.core.resolve_engine import execute_remediation_agent
    from backend.database import SessionLocal

    def _run():
        _db = SessionLocal()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(execute_remediation_agent(session_id, body.agent_id, _db, user=current_user))
            loop.close()
        except Exception as exc:
            logger.error("Background agent remediation failed: %s", exc)
        finally:
            _db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {"status": "executing", "session_id": session_id}


# 9. Get results

@router.get("/sessions/{session_id}/results", response_model=list[ResolveItemResponse])
def get_resolve_results(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    items = (
        db.query(RemediationItem)
        .filter(RemediationItem.session_id == session_id)
        .order_by(RemediationItem.order_index)
        .all()
    )
    return items


# 10. Export results CSV

@router.get("/sessions/{session_id}/results/csv")
def export_resolve_results_csv(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session = db.query(RemediationSession).filter(RemediationSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    from backend.core.resolve_engine import export_results_csv

    csv_bytes = export_results_csv(session_id, db)

    log_action(
        db, user=current_user, mission_id=session.mission_id,
        action="resolve_results_exported",
        entity_type="remediation_session", entity_id=session_id,
    )
    db.commit()

    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="resolve_{session_id}_results.csv"'},
    )


# 11. Scan Intelligence

@router.post("/scan-intelligence", response_model=ScanIntelligenceResponse)
def get_scan_intelligence(
    body: ScanIntelligenceRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from backend.core.resolve_engine import build_scan_intelligence

    result = build_scan_intelligence(body.target_id, body.scan_ids, db)
    return result


# Delete session

@router.delete("/sessions/{session_id}")
def delete_resolve_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session = db.query(RemediationSession).filter(RemediationSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    if session.status in ("executing",):
        raise HTTPException(409, "Cannot delete an executing session")

    log_action(
        db, user=current_user, mission_id=session.mission_id,
        action="resolve_session_deleted",
        entity_type="remediation_session", entity_id=session_id,
    )

    db.delete(session)
    db.commit()
    return {"deleted": True}
