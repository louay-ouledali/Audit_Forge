"""Pydantic schemas for AuditForge Connect."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


# ── Request schemas ───────────────────────────────────────────────

class ConnectSessionCreate(BaseModel):
    client_id: int
    mission_id: int | None = None
    expires_in_hours: int = 24
    max_agent_lifetime_seconds: int = 14400  # 4 hours
    notes: str | None = None


class AgentScanRequest(BaseModel):
    benchmark_id: int
    agent_ids: list[int] | None = None  # None = scan all connected agents


# ── Response schemas ──────────────────────────────────────────────

class ConnectAgentResponse(BaseModel):
    id: int
    session_id: int
    hostname: str | None
    ip_address: str | None
    os_type: str | None
    os_version: str | None
    status: str
    connected_at: datetime | None
    disconnected_at: datetime | None
    target_id: int | None
    system_info: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class ConnectSessionResponse(BaseModel):
    id: int
    enrollment_code: str
    client_id: int
    mission_id: int | None = None
    status: str
    created_at: datetime
    expires_at: datetime
    max_agent_lifetime_seconds: int
    notes: str | None
    agent_count: int = 0
    agents: list[ConnectAgentResponse] = []

    model_config = {"from_attributes": True}


class PortalValidation(BaseModel):
    valid: bool
    session_id: int | None = None
    client_name: str | None = None
    expires_at: datetime | None = None
