from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TargetCreate(BaseModel):
    mission_id: int
    hostname: str | None = None
    ip_address: str | None = None
    target_type: str
    os_details: str | None = None
    connection_method: str | None = None
    ssh_username: str | None = None
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    port: int | None = None
    db_connection_string: str | None = None
    notes: str | None = None


class TargetUpdate(BaseModel):
    hostname: str | None = None
    ip_address: str | None = None
    target_type: str | None = None
    os_details: str | None = None
    connection_method: str | None = None
    ssh_username: str | None = None
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    port: int | None = None
    db_connection_string: str | None = None
    notes: str | None = None


class TargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mission_id: int
    hostname: str | None = None
    ip_address: str | None = None
    target_type: str
    os_details: str | None = None
    connection_method: str | None = None
    ssh_username: str | None = None
    ssh_key_path: str | None = None
    port: int | None = None
    notes: str | None = None
    created_at: datetime | None = None


class TargetDetailEnvelope(BaseModel):
    data: TargetResponse
    message: str = "success"


class TargetListResponse(BaseModel):
    data: list[TargetResponse]
    total: int
