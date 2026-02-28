"""Pydantic schemas for saved reports."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SavedReportCreate(BaseModel):
    mission_id: int | None = None
    name: str
    description: str | None = None
    scope: str | None = None
    scope_id: int | None = None
    scan_ids_json: str | None = None
    config_json: str | None = None
    format: str = "html"


class SavedReportUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config_json: str | None = None
    format: str | None = None
    status: str | None = None


class SavedReportResponse(BaseModel):
    id: int
    mission_id: int | None = None
    name: str
    description: str | None = None
    scope: str | None = None
    scope_id: int | None = None
    scan_ids_json: str | None = None
    config_json: str | None = None
    format: str
    file_size_kb: float | None = None
    ai_enhanced: str = "none"
    ai_enhanced_at: datetime | None = None
    status: str = "draft"
    generated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SavedReportDetailEnvelope(BaseModel):
    data: SavedReportResponse
    message: str = "success"


class SavedReportListResponse(BaseModel):
    data: list[SavedReportResponse]
    total: int
