from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClientCreate(BaseModel):
    name: str
    industry: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    notes: str | None = None


class ClientUpdate(BaseModel):
    name: str | None = None
    industry: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    notes: str | None = None


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    industry: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    notes: str | None = None
    created_at: datetime | None = None
    mission_count: int = 0


class ClientDetailEnvelope(BaseModel):
    data: ClientResponse
    message: str = "success"


class ClientListResponse(BaseModel):
    data: list[ClientResponse]
    total: int
