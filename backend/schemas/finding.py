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
    expected_output_display: str | None = None
    evaluation_explanation: str | None = None
    severity: str | None = None
    ai_advice: str | None = None
    ai_advice_generated_at: datetime | None = None
    auditor_notes: str | None = None
    auditor_override: str | None = None
    created_at: datetime | None = None

    # Auditor override fields
    auditor_status_override: str | None = None
    auditor_severity_override: str | None = None
    auditor_description: str | None = None
    auditor_remediation: str | None = None
    override_reason: str | None = None
    overridden_at: datetime | None = None

    # Joined fields from rule
    section_number: str | None = None
    rule_title: str | None = None

    model_config = {"from_attributes": True}


class FindingUpdateRequest(BaseModel):
    auditor_notes: str | None = None
    auditor_override: str | None = None
    auditor_status_override: str | None = None
    auditor_severity_override: str | None = None
    auditor_description: str | None = None
    auditor_remediation: str | None = None
    override_reason: str | None = None


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
