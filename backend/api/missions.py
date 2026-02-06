from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.client import Client
from backend.models.mission import Mission
from backend.schemas.mission import (
    MissionCreate,
    MissionDetailEnvelope,
    MissionListResponse,
    MissionResponse,
    MissionUpdate,
)

router = APIRouter(tags=["missions"])


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
    db.delete(mission)
    db.commit()
    return {"data": None, "message": "Mission deleted"}
