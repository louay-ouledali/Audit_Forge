from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class MissionCreate(BaseModel):
    client_id: int
    name: str
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str = "in_progress"
    notes: str | None = None


class MissionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    notes: str | None = None


class MissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    name: str
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    notes: str | None = None
    created_at: datetime | None = None
    target_count: int = 0


class MissionDetailEnvelope(BaseModel):
    data: MissionResponse
    message: str = "success"


class MissionListResponse(BaseModel):
    data: list[MissionResponse]
    total: int
