from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RuleTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tag_id: str
    source: str = "auto"


class RuleTagCreate(BaseModel):
    tag_id: str
    source: str = "auditor"


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    benchmark_id: int
    section_number: str
    title: str
    description: str | None = None
    rationale: str | None = None
    profile_applicability: str | None = None
    assessment_type: str | None = None
    default_value: str | None = None
    references_json: str | None = None
    audit_description_raw: str | None = None
    remediation_description_raw: str | None = None
    severity: str = "medium"
    enabled: bool = True
    tags: list[RuleTagResponse] = []


class RuleUpdate(BaseModel):
    severity: str | None = None
    enabled: bool | None = None


class RuleCommandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: int
    audit_command: str | None = None
    expected_output_regex: str | None = None
    expected_output_description: str | None = None
    remediation_command: str | None = None
    remediation_description: str | None = None
    status: str = "generated"
    source: str = "llm_generated"
    is_protected: bool = False
    protection_reason: str | None = None
    protected_at: datetime | None = None
    verified_at: datetime | None = None
    verification_notes: str | None = None
    flagged_at: datetime | None = None
    flag_reason: str | None = None
    regeneration_count: int = 0
    last_regenerated_at: datetime | None = None


class RuleCommandUpdate(BaseModel):
    audit_command: str | None = None
    expected_output_regex: str | None = None
    expected_output_description: str | None = None
    remediation_command: str | None = None
    remediation_description: str | None = None


class FlagCommandRequest(BaseModel):
    reason: str
    error_output: str | None = None


class RegenerateCommandRequest(BaseModel):
    system_info: str | None = None


class ProtectCommandRequest(BaseModel):
    reason: str | None = "Manually protected by auditor"


class UnlockCommandRequest(BaseModel):
    reason: str


class CommandHistoryEntry(BaseModel):
    audit_command: str | None = None
    expected_output_regex: str | None = None
    flag_reason: str | None = None
    source: str | None = None
    timestamp: str | None = None


class CommandHistoryResponse(BaseModel):
    data: list[CommandHistoryEntry]
    total: int
    message: str = "success"


class VerificationReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_command_id: int
    level: str
    result: str
    message: str | None = None
    details: str | None = None
    auto_fixable: bool = False
    run_at: datetime | None = None


class VerificationResultsResponse(BaseModel):
    data: list[VerificationReportResponse]
    total: int
    message: str = "success"


class RuleListResponse(BaseModel):
    data: list[RuleResponse]
    total: int


class RuleDetailEnvelope(BaseModel):
    data: RuleResponse
    message: str = "success"


class RuleCommandEnvelope(BaseModel):
    data: RuleCommandResponse | None = None
    message: str = "success"


class RuleTagEnvelope(BaseModel):
    data: list[RuleTagResponse]
    message: str = "success"
