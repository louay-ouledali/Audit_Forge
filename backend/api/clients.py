from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.client import Client
from backend.schemas.client import (
    ClientCreate,
    ClientDetailEnvelope,
    ClientListResponse,
    ClientResponse,
    ClientUpdate,
)

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=ClientListResponse)
def list_clients(db: Session = Depends(get_db)) -> dict:
    clients = db.query(Client).order_by(Client.id).all()
    result = []
    for c in clients:
        resp = ClientResponse.model_validate(c)
        resp.mission_count = len(c.missions)
        result.append(resp)
    return {"data": result, "total": len(result)}


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
    resp.mission_count = len(client.missions)
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
    resp.mission_count = len(client.missions)
    return {"data": resp, "message": "Client updated"}


@router.delete("/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(client)
    db.commit()
    return {"data": None, "message": "Client deleted"}
