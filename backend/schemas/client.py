from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClientCreate(BaseModel):
    name: str
    industry: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    notes: str | None = None
    # AD credential fields (optional at creation)
    ad_domain: str | None = None
    ad_dc_host: str | None = None
    ad_username: str | None = None
    ad_password: str | None = None        # plaintext → encrypted on save
    ad_use_ssl: bool | None = True
    ad_base_ou: str | None = None


class ClientUpdate(BaseModel):
    name: str | None = None
    industry: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    notes: str | None = None
    ad_domain: str | None = None
    ad_dc_host: str | None = None
    ad_username: str | None = None
    ad_password: str | None = None        # plaintext → encrypted on save
    ad_use_ssl: bool | None = None
    ad_base_ou: str | None = None


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
    # AD fields (password is NEVER returned)
    ad_domain: str | None = None
    ad_dc_host: str | None = None
    ad_username: str | None = None
    ad_use_ssl: bool | None = None
    ad_base_ou: str | None = None
    ad_configured: bool = False       # convenience flag


class ClientDetailEnvelope(BaseModel):
    data: ClientResponse
    message: str = "success"


class ClientListResponse(BaseModel):
    data: list[ClientResponse]
    total: int
