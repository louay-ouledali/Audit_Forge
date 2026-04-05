from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.core.auth import get_current_user
from backend.core.trail import log_action
from backend.models.client import Client
from backend.models.mission import Mission
from backend.models.target import Target  # UNUSED — safe to remove
from backend.models.mission_target import MissionTarget
from backend.models.user import User
from backend.schemas.mission import (
    MissionCreate,
    MissionDetailEnvelope,
    MissionListResponse,
    MissionLockRequest,
    MissionResponse,
    MissionUnlockRequest,
    MissionUpdate,
)

router = APIRouter(tags=["missions"])
logger = logging.getLogger("auditforge.api.missions")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def check_mission_lock(mission_id: int | None, db: Session) -> None:
    """Raise 403 if the mission is locked. Call this before any mutation
    on data that belongs to a locked mission (findings, scans, targets).

    If *mission_id* is ``None``, the check is silently skipped.
    """
    if mission_id is None:
        return
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if mission and mission.is_locked:
        raise HTTPException(
            status_code=403,
            detail="Mission is locked. Unlock it before making changes.",
        )


def _target_count(db: Session, mission_id: int) -> int:
    """Efficient target count without loading the full relationship."""
    return (
        db.query(func.count(MissionTarget.id))
        .filter(MissionTarget.mission_id == mission_id)
        .scalar()
        or 0
    )


def _batch_target_counts(db: Session, mission_ids: list[int]) -> dict[int, int]:
    """Batch-fetch target counts for multiple missions in one query."""
    if not mission_ids:
        return {}
    rows = (
        db.query(MissionTarget.mission_id, func.count(MissionTarget.id))
        .filter(MissionTarget.mission_id.in_(mission_ids))
        .group_by(MissionTarget.mission_id)
        .all()
    )
    return dict(rows)


@router.get("/missions", response_model=MissionListResponse)
def list_all_missions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """List all missions across all clients."""
    total = db.query(func.count(Mission.id)).scalar() or 0
    missions = db.query(Mission).order_by(Mission.id.desc()).offset(skip).limit(limit).all()

    counts_map = _batch_target_counts(db, [m.id for m in missions])

    result = []
    for m in missions:
        resp = MissionResponse.model_validate(m)
        resp.target_count = counts_map.get(m.id, 0)
        resp.client_name = m.client.name if m.client else None
        result.append(resp)
    return {"data": result, "total": total}


@router.get("/clients/{client_id}/missions", response_model=MissionListResponse)
def list_missions(
    client_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    base = db.query(Mission).filter(Mission.client_id == client_id)
    total = base.count()
    missions = base.order_by(Mission.id).offset(skip).limit(limit).all()

    counts_map = _batch_target_counts(db, [m.id for m in missions])

    result = []
    for m in missions:
        resp = MissionResponse.model_validate(m)
        resp.target_count = counts_map.get(m.id, 0)
        result.append(resp)
    return {"data": result, "total": total}


@router.post("/missions", response_model=MissionDetailEnvelope, status_code=201)
def create_mission(payload: MissionCreate, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == payload.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    mission = Mission(**payload.model_dump())
    db.add(mission)
    db.commit()
    db.refresh(mission)
    log_action(db, mission_id=mission.id, action="mission_created", entity_type="mission", entity_id=mission.id, entity_label=mission.name)
    db.commit()
    resp = MissionResponse.model_validate(mission)
    resp.target_count = 0
    return {"data": resp, "message": "Mission created"}


@router.get("/missions/{mission_id}", response_model=MissionDetailEnvelope)
def get_mission(mission_id: int, db: Session = Depends(get_db)) -> dict:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    resp = MissionResponse.model_validate(mission)
    resp.target_count = _target_count(db, mission_id)
    return {"data": resp, "message": "success"}


@router.put("/missions/{mission_id}", response_model=MissionDetailEnvelope)
def update_mission(mission_id: int, payload: MissionUpdate, db: Session = Depends(get_db)) -> dict:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    if mission.is_locked:
        raise HTTPException(status_code=403, detail="Mission is locked. Unlock it first.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(mission, field, value)
    log_action(db, mission_id=mission_id, action="mission_updated", entity_type="mission", entity_id=mission_id, entity_label=mission.name)
    db.commit()
    db.refresh(mission)
    resp = MissionResponse.model_validate(mission)
    resp.target_count = _target_count(db, mission_id)
    return {"data": resp, "message": "Mission updated"}


@router.delete("/missions/{mission_id}")
def delete_mission(mission_id: int, db: Session = Depends(get_db)) -> dict:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    if mission.is_locked:
        raise HTTPException(status_code=403, detail="Mission is locked. Unlock it before deleting.")
    mission_name = mission.name
    db.delete(mission)
    log_action(db, mission_id=mission_id, action="mission_deleted", entity_type="mission", entity_id=mission_id, entity_label=mission_name)
    db.commit()
    return {"data": None, "message": "Mission deleted"}


# ── Mission Locking ──────────────────────────────────────────


@router.post("/missions/{mission_id}/lock")
def lock_mission(
    mission_id: int, payload: MissionLockRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
) -> dict:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    if mission.is_locked:
        raise HTTPException(status_code=400, detail="Mission is already locked")

    mission.is_locked = True
    mission.password_hash = _hash_password(payload.password)
    mission.locked_at = datetime.now(timezone.utc)
    mission.locked_by = "auditor"  # placeholder — can be enriched with auth later
    db.commit()
    try:
        log_action(db, user=current_user, mission_id=mission_id, action="mission_locked", entity_type="mission", entity_id=mission_id, entity_label=mission.name)
    except Exception as exc:
        logger.warning("Trail log failed: %s", exc)
    db.refresh(mission)
    resp = MissionResponse.model_validate(mission)
    resp.target_count = _target_count(db, mission_id)
    return {"data": resp, "message": "Mission locked"}


@router.post("/missions/{mission_id}/unlock")
def unlock_mission(
    mission_id: int, payload: MissionUnlockRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
) -> dict:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    if not mission.is_locked:
        raise HTTPException(status_code=400, detail="Mission is not locked")

    if mission.password_hash != _hash_password(payload.password):
        raise HTTPException(status_code=403, detail="Invalid password")

    mission.is_locked = False
    mission.password_hash = None
    mission.locked_at = None
    mission.locked_by = None
    db.commit()
    try:
        log_action(db, user=current_user, mission_id=mission_id, action="mission_unlocked", entity_type="mission", entity_id=mission_id, entity_label=mission.name)
    except Exception as exc:
        logger.warning("Trail log failed: %s", exc)
    db.refresh(mission)
    resp = MissionResponse.model_validate(mission)
    resp.target_count = _target_count(db, mission_id)
    return {"data": resp, "message": "Mission unlocked"}


@router.post("/missions/{mission_id}/verify-lock")
def verify_mission_lock(
    mission_id: int, payload: MissionUnlockRequest, db: Session = Depends(get_db)
) -> dict:
    """Verify the lock password without unlocking the mission."""
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    if not mission.is_locked:
        return {"valid": True, "message": "Mission is not locked"}
    valid = mission.password_hash == _hash_password(payload.password)
    if not valid:
        raise HTTPException(status_code=403, detail="Invalid password")
    return {"valid": True, "message": "Password verified"}
