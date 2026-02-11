"""Pydantic schemas for post-mission AI analysis."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AnalysisRequest(BaseModel):
    analysis_type: str  # "cross_target", "cross_mission", "category_analysis"
    compare_mission_id: int | None = None  # required only for "cross_mission"


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mission_id: int
    analysis_type: str
    compared_mission_id: int | None = None
    result: Any
    llm_model_used: str | None = None
    generated_at: datetime | None = None


class AnalysisListResponse(BaseModel):
    data: list[AnalysisResponse]
    total: int


class AnalysisDetailEnvelope(BaseModel):
    data: AnalysisResponse
    message: str = "success"


class ComparableMission(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    start_date: str | None = None
    end_date: str | None = None
    compliance: float | None = None


class ComparableMissionListResponse(BaseModel):
    data: list[ComparableMission]
