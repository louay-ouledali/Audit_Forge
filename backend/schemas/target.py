from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TargetCreate(BaseModel):
    client_id: int
    hostname: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    target_type: str
    os_details: str | None = None
    connection_method: str | None = None
    ssh_username: str | None = None
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    port: int | None = None
    db_connection_string: str | None = None
    notes: str | None = None
    # Phase 1 — scanning enhancements
    platform_subtype: str | None = None
    default_benchmark_id: int | None = None
    db_name: str | None = None
    db_instance: str | None = None
    enable_password: str | None = None   # write-only, encrypted on save
    device_type: str | None = None
    config_pull_method: str | None = None


class TargetUpdate(BaseModel):
    hostname: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    target_type: str | None = None
    os_details: str | None = None
    connection_method: str | None = None
    ssh_username: str | None = None
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    port: int | None = None
    db_connection_string: str | None = None
    notes: str | None = None
    # Phase 1 — scanning enhancements
    platform_subtype: str | None = None
    default_benchmark_id: int | None = None
    db_name: str | None = None
    db_instance: str | None = None
    enable_password: str | None = None
    device_type: str | None = None
    config_pull_method: str | None = None


class TargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    hostname: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    target_type: str
    os_details: str | None = None
    connection_method: str | None = None
    ssh_username: str | None = None
    ssh_key_path: str | None = None
    port: int | None = None
    notes: str | None = None
    created_at: datetime | None = None
    # Phase 1 — scanning enhancements
    platform_subtype: str | None = None
    default_benchmark_id: int | None = None
    default_benchmark_name: str | None = None   # computed via join
    last_connection_test: datetime | None = None
    connection_status: str | None = None
    connection_error: str | None = None
    db_name: str | None = None
    db_instance: str | None = None
    has_enable_password: bool = False            # never expose actual password
    device_type: str | None = None
    config_pull_method: str | None = None
    latest_config_id: int | None = None
    verify_tls: bool = True
    last_scan_compliance: float | None = None    # computed from most recent scan
    last_scan_date: datetime | None = None       # computed
    scan_count: int = 0                          # computed


class TargetDetailEnvelope(BaseModel):
    data: TargetResponse
    message: str = "success"


class TargetListResponse(BaseModel):
    data: list[TargetResponse]
    total: int
