from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict


# ── Requests ──────────────────────────────────────────────────────────

class ResolveSessionCreate(BaseModel):
    mission_id: int
    target_id: int
    scan_ids: list[int]


class ResolveItemUpdate(BaseModel):
    selected: bool | None = None
    remediation_command: str | None = None
    order_index: int | None = None


class BulkSelectRequest(BaseModel):
    item_ids: list[int]
    selected: bool


class ExecuteRequest(BaseModel):
    confirm_privilege: bool = False
    current_password: str | None = None


class AgentExecuteRequest(BaseModel):
    agent_id: int
    confirm_privilege: bool = False
    current_password: str | None = None


class ScanIntelligenceRequest(BaseModel):
    target_id: int
    scan_ids: list[int]


# ── Responses ─────────────────────────────────────────────────────────

class ResolveItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    finding_id: int | None = None
    rule_id: int | None = None
    section_number: str
    rule_title: str
    severity: str | None = None
    remediation_command: str | None = None
    command_source: str
    command_transport: str | None = None
    selected: bool
    status: str
    execution_output: str | None = None
    execution_error: str | None = None
    executed_at: datetime | None = None
    order_index: int
    requires_privilege: bool


class ResolveSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mission_id: int
    target_id: int
    created_by: str
    status: str
    execution_mode: str | None = None
    created_at: datetime | None = None
    executed_at: datetime | None = None
    completed_at: datetime | None = None
    total_items: int
    succeeded_items: int
    failed_items: int
    skipped_items: int
    notes: str | None = None
    scan_ids_json: str | None = None
    items: list[ResolveItemResponse] = []


class ResolveSessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    execution_mode: str | None = None
    created_at: datetime | None = None
    total_items: int
    succeeded_items: int
    failed_items: int


# ── Scan Intelligence ─────────────────────────────────────────────────

class ScanSummary(BaseModel):
    scan_id: int
    date: str
    compliance: float
    passed: int
    failed: int
    errors: int


class DeltaRule(BaseModel):
    rule_id: int
    section_number: str
    title: str
    severity: str | None = None
    history: list[dict] = []
    change_type: str  # improved | regressed | new | removed | unchanged
    remediation_command: str | None = None
    has_executable_command: bool = False


class AiInsights(BaseModel):
    summary: str
    risk_trajectory: str  # improving | stable | declining
    patterns: list[str] = []
    priority_remediations: list[str] = []


class ScanIntelligenceResponse(BaseModel):
    scans: list[ScanSummary] = []
    time_intervals: list[str] = []
    compliance_trend: list[dict] = []
    rules_improved: int = 0
    rules_regressed: int = 0
    rules_unchanged: int = 0
    rules_new: int = 0
    rules_removed: int = 0
    changed_rules: list[DeltaRule] = []
    consistent_rules: list[DeltaRule] = []
    ai_insights: AiInsights | None = None
