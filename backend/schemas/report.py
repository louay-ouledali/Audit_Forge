"""Pydantic schemas for report generation."""
from __future__ import annotations

from pydantic import BaseModel


class ReportGenerateRequest(BaseModel):
    scope: str  # "scan", "target", "mission", "custom"
    scope_id: int | None = None
    scan_ids: list[int] | None = None  # for "custom" scope
    format: str  # "pdf", "excel", "csv", "html"
    include_ai_summary: bool = False
    include_passed_rules: bool = True
    title: str | None = None


class AISummaryRequest(BaseModel):
    scope: str  # "scan", "target", "mission"
    scope_id: int


class AISummaryResponse(BaseModel):
    summary: str
