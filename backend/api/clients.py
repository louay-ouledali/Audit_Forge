from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import settings
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
from backend.utils.encryption import encrypt_value
from backend.core.trail import log_action
from backend.core.auth import get_current_user
from backend.models.user import User

router = APIRouter(prefix="/clients", tags=["clients"])


def _client_mission_count(db: Session, client_id: int) -> int:
    """Efficient mission count without loading the full relationship."""
    return db.query(func.count(Mission.id)).filter(Mission.client_id == client_id).scalar() or 0


def _build_response(client: Client, mission_count: int) -> ClientResponse:
    """Build a ClientResponse with computed ad_configured flag."""
    resp = ClientResponse.model_validate(client)
    resp.mission_count = mission_count
    resp.ad_configured = bool(client.ad_domain and client.ad_dc_host and client.ad_username and client.ad_password_encrypted)
    resp.ad_use_ssl = bool(client.ad_use_ssl) if client.ad_use_ssl is not None else None
    return resp


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
        resp = _build_response(c, counts_map.get(c.id, 0))
        result.append(resp)
    return {"data": result, "total": total}


@router.post("", response_model=ClientDetailEnvelope, status_code=201)
def create_client(payload: ClientCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    data = payload.model_dump(exclude={"ad_password"})
    # Encrypt AD password if provided
    if payload.ad_password:
        data["ad_password_encrypted"] = encrypt_value(payload.ad_password, settings.effective_encryption_key)
    # Store ad_use_ssl as integer in DB
    if data.get("ad_use_ssl") is not None:
        data["ad_use_ssl"] = 1 if data["ad_use_ssl"] else 0
    client = Client(**data)
    db.add(client)
    db.commit()
    db.refresh(client)
    log_action(db, user=current_user, action="client_created", entity_type="client", entity_id=client.id, entity_label=client.name)
    db.commit()
    return {"data": _build_response(client, 0), "message": "Client created"}


@router.get("/{client_id}", response_model=ClientDetailEnvelope)
def get_client(client_id: int, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"data": _build_response(client, _client_mission_count(db, client_id)), "message": "success"}


@router.put("/{client_id}", response_model=ClientDetailEnvelope)
def update_client(client_id: int, payload: ClientUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    updates = payload.model_dump(exclude_unset=True, exclude={"ad_password"})
    # Encrypt AD password if provided
    if payload.ad_password is not None:
        if payload.ad_password:
            updates["ad_password_encrypted"] = encrypt_value(payload.ad_password, settings.effective_encryption_key)
        else:
            updates["ad_password_encrypted"] = None  # clear password
    # Store ad_use_ssl as integer in DB
    if "ad_use_ssl" in updates and updates["ad_use_ssl"] is not None:
        updates["ad_use_ssl"] = 1 if updates["ad_use_ssl"] else 0
    for field, value in updates.items():
        setattr(client, field, value)
    log_action(db, user=current_user, action="client_updated", entity_type="client", entity_id=client_id, entity_label=client.name)
    db.commit()
    db.refresh(client)
    return {"data": _build_response(client, _client_mission_count(db, client_id)), "message": "Client updated"}


@router.delete("/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client_name = client.name
    db.delete(client)
    log_action(db, user=current_user, action="client_deleted", entity_type="client", entity_id=client_id, entity_label=client_name)
    db.commit()
    return {"data": None, "message": "Client deleted"}
