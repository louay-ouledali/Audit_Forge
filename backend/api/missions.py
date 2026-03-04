from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.client import Client
from backend.models.mission import Mission
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


@router.get("/missions", response_model=MissionListResponse)
def list_all_missions(db: Session = Depends(get_db)) -> dict:
    """List all missions across all clients."""
    missions = db.query(Mission).order_by(Mission.id.desc()).all()
    result = []
    for m in missions:
        resp = MissionResponse.model_validate(m)
        resp.target_count = len(m.targets)
        resp.client_name = m.client.name if m.client else None
        result.append(resp)
    return {"data": result, "total": len(result)}


@router.get("/clients/{client_id}/missions", response_model=MissionListResponse)
def list_missions(client_id: int, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    missions = db.query(Mission).filter(Mission.client_id == client_id).order_by(Mission.id).all()
    result = []
    for m in missions:
        resp = MissionResponse.model_validate(m)
        resp.target_count = len(m.targets)
        result.append(resp)
    return {"data": result, "total": len(result)}


@router.post("/missions", response_model=MissionDetailEnvelope, status_code=201)
def create_mission(payload: MissionCreate, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == payload.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    mission = Mission(**payload.model_dump())
    db.add(mission)
    db.commit()
    db.refresh(mission)
    resp = MissionResponse.model_validate(mission)
    resp.target_count = 0
    return {"data": resp, "message": "Mission created"}


@router.get("/missions/{mission_id}", response_model=MissionDetailEnvelope)
def get_mission(mission_id: int, db: Session = Depends(get_db)) -> dict:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    resp = MissionResponse.model_validate(mission)
    resp.target_count = len(mission.targets)
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
    db.commit()
    db.refresh(mission)
    resp = MissionResponse.model_validate(mission)
    resp.target_count = len(mission.targets)
    return {"data": resp, "message": "Mission updated"}


@router.delete("/missions/{mission_id}")
def delete_mission(mission_id: int, db: Session = Depends(get_db)) -> dict:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    if mission.is_locked:
        raise HTTPException(status_code=403, detail="Mission is locked. Unlock it before deleting.")
    db.delete(mission)
    db.commit()
    return {"data": None, "message": "Mission deleted"}


# ── Mission Locking ──────────────────────────────────────────


@router.post("/missions/{mission_id}/lock")
def lock_mission(
    mission_id: int, payload: MissionLockRequest, db: Session = Depends(get_db)
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
    db.refresh(mission)
    resp = MissionResponse.model_validate(mission)
    resp.target_count = len(mission.targets)
    return {"data": resp, "message": "Mission locked"}


@router.post("/missions/{mission_id}/unlock")
def unlock_mission(
    mission_id: int, payload: MissionUnlockRequest, db: Session = Depends(get_db)
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
    db.refresh(mission)
    resp = MissionResponse.model_validate(mission)
    resp.target_count = len(mission.targets)
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
