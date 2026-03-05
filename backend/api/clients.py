from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.client import Client
from backend.models.mission import Mission
from backend.schemas.client import (
    ClientCreate,
    ClientDetailEnvelope,
    ClientListResponse,
    ClientResponse,
    ClientUpdate,
)

router = APIRouter(prefix="/clients", tags=["clients"])


def _client_mission_count(db: Session, client_id: int) -> int:
    """Efficient mission count without loading the full relationship."""
    return db.query(func.count(Mission.id)).filter(Mission.client_id == client_id).scalar() or 0


@router.get("", response_model=ClientListResponse)
def list_clients(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    total = db.query(func.count(Client.id)).scalar() or 0
    clients = db.query(Client).order_by(Client.id).offset(skip).limit(limit).all()

    # Batch-fetch mission counts with a single query
    client_ids = [c.id for c in clients]
    count_rows = (
        db.query(Mission.client_id, func.count(Mission.id))
        .filter(Mission.client_id.in_(client_ids))
        .group_by(Mission.client_id)
        .all()
    ) if client_ids else []
    counts_map = dict(count_rows)

    result = []
    for c in clients:
        resp = ClientResponse.model_validate(c)
        resp.mission_count = counts_map.get(c.id, 0)
        result.append(resp)
    return {"data": result, "total": total}


@router.post("", response_model=ClientDetailEnvelope, status_code=201)
def create_client(payload: ClientCreate, db: Session = Depends(get_db)) -> dict:
    client = Client(**payload.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    resp = ClientResponse.model_validate(client)
    resp.mission_count = 0
    return {"data": resp, "message": "Client created"}


@router.get("/{client_id}", response_model=ClientDetailEnvelope)
def get_client(client_id: int, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    resp = ClientResponse.model_validate(client)
    resp.mission_count = _client_mission_count(db, client_id)
    return {"data": resp, "message": "success"}


@router.put("/{client_id}", response_model=ClientDetailEnvelope)
def update_client(client_id: int, payload: ClientUpdate, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    db.commit()
    db.refresh(client)
    resp = ClientResponse.model_validate(client)
    resp.mission_count = _client_mission_count(db, client_id)
    return {"data": resp, "message": "Client updated"}


@router.delete("/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(client)
    db.commit()
    return {"data": None, "message": "Client deleted"}
