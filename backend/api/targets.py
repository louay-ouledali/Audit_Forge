from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.mission import Mission
from backend.models.target import Target
from backend.schemas.target import (
    TargetCreate,
    TargetDetailEnvelope,
    TargetListResponse,
    TargetResponse,
    TargetUpdate,
)
from backend.utils.encryption import decrypt_value, encrypt_value

router = APIRouter(tags=["targets"])


def _encrypt_fields(data: dict) -> dict:
    """Encrypt sensitive fields before storing."""
    if data.get("ssh_password"):
        data["ssh_password_encrypted"] = encrypt_value(data.pop("ssh_password"), settings.SECRET_KEY)
    else:
        data.pop("ssh_password", None)

    if data.get("db_connection_string"):
        data["db_connection_string_encrypted"] = encrypt_value(
            data.pop("db_connection_string"), settings.SECRET_KEY
        )
    else:
        data.pop("db_connection_string", None)

    return data


@router.get("/missions/{mission_id}/targets", response_model=TargetListResponse)
def list_targets(mission_id: int, db: Session = Depends(get_db)) -> dict:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    targets = db.query(Target).filter(Target.mission_id == mission_id).order_by(Target.id).all()
    result = [TargetResponse.model_validate(t) for t in targets]
    return {"data": result, "total": len(result)}


@router.post("/targets", response_model=TargetDetailEnvelope, status_code=201)
def create_target(payload: TargetCreate, db: Session = Depends(get_db)) -> dict:
    mission = db.query(Mission).filter(Mission.id == payload.mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    data = _encrypt_fields(payload.model_dump())
    target = Target(**data)
    db.add(target)
    db.commit()
    db.refresh(target)
    resp = TargetResponse.model_validate(target)
    return {"data": resp, "message": "Target created"}


@router.get("/targets/{target_id}", response_model=TargetDetailEnvelope)
def get_target(target_id: int, db: Session = Depends(get_db)) -> dict:
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    resp = TargetResponse.model_validate(target)
    return {"data": resp, "message": "success"}


@router.put("/targets/{target_id}", response_model=TargetDetailEnvelope)
def update_target(target_id: int, payload: TargetUpdate, db: Session = Depends(get_db)) -> dict:
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    data = _encrypt_fields(payload.model_dump(exclude_unset=True))
    for field, value in data.items():
        setattr(target, field, value)
    db.commit()
    db.refresh(target)
    resp = TargetResponse.model_validate(target)
    return {"data": resp, "message": "Target updated"}


@router.delete("/targets/{target_id}")
def delete_target(target_id: int, db: Session = Depends(get_db)) -> dict:
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    db.delete(target)
    db.commit()
    return {"data": None, "message": "Target deleted"}
