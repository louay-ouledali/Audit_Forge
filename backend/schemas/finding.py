"""Pydantic schemas for findings."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FindingResponse(BaseModel):
    id: int
    scan_id: int
    rule_id: int
    status: str
    actual_output: str | None = None
    expected_output: str | None = None
    expected_output_display: str | None = None  # Human-readable form of expected_output
    evaluation_explanation: str | None = None  # How the comparison was evaluated
    severity: str | None = None
    ai_advice: str | None = None
    ai_advice_generated_at: datetime | None = None
    auditor_notes: str | None = None
    auditor_override: str | None = None
    created_at: datetime | None = None

    # Joined fields from rule
    section_number: str | None = None
    rule_title: str | None = None

    model_config = {"from_attributes": True}


class FindingUpdateRequest(BaseModel):
    auditor_notes: str | None = None
    auditor_override: str | None = None  # confirmed, false_positive, accepted_risk


class FindingAIAdviceResponse(BaseModel):
    advice: str
    generated_at: datetime


class ImportResultsResponse(BaseModel):
    findings_created: int
    passed: int
    failed: int
    errors: int
    compliance_percentage: float


class ImportWithScanResponse(ImportResultsResponse):
    scan_id: int


class ScanResponse(BaseModel):
    id: int
    target_id: int
    benchmark_id: int
    scan_mode: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    results_imported_at: datetime | None = None
    total_rules_checked: int
    passed: int
    failed: int
    errors: int
    not_applicable: int
    manual_review: int
    compliance_percentage: float | None = None
    notes: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ScanListResponse(BaseModel):
    data: list[ScanResponse]
    total: int
