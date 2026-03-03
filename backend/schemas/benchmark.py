from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BenchmarkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: str
    platform: str
    platform_family: str
    import_date: datetime | None = None
    pdf_filename: str | None = None
    total_rules: int = 0
    phase1_status: str = "pending"
    phase2_status: str = "pending"
    verification_status: str = "pending"
    phase3_status: str | None = None
    is_ready: bool = False
    status: str = "active"
    notes: str | None = None
    # Phase 1 / Benchmark Studio fields
    is_editable: bool = False
    parent_benchmark_id: int | None = None
    migration_readiness: float | None = None
    source: str | None = None
    source_details: str | None = None


class BenchmarkDetailEnvelope(BaseModel):
    data: BenchmarkResponse
    message: str = "success"


class BenchmarkListResponse(BaseModel):
    data: list[BenchmarkResponse]
    total: int


class BenchmarkImportResponse(BaseModel):
    benchmark_id: int
    status: str = "processing"
    message: str = "PDF import started"


class BenchmarkStatusResponse(BaseModel):
    id: int
    phase1_status: str
    phase2_status: str
    verification_status: str
    phase3_status: str | None = None
    is_ready: bool
    total_rules: int


class EnrichStatusResponse(BaseModel):
    total: int = 0
    processed: int = 0
    template_matched: int = 0
    llm_generated: int = 0
    status: str = "pending"


class VerifyStatusResponse(BaseModel):
    status: str
    total: int = 0
    passed: int = 0
    failed: int = 0


class ValidateStatusResponse(BaseModel):
    status: str
    total: int = 0
    processed: int = 0
    validated: int = 0
    corrected: int = 0
    flagged: int = 0


class ValidationCorrection(BaseModel):
    field: str
    old_value: str
    new_value: str
    reason: str


class ValidationResultItem(BaseModel):
    rule_command_id: int
    rule_id: int
    section_number: str
    title: str
    validation_status: str | None = None
    validation_confidence: str | None = None
    corrections: list[ValidationCorrection] = []
    notes: str | None = None
    audit_command: str | None = None
    expected_output_regex: str | None = None


class ValidationResultsResponse(BaseModel):
    data: list[ValidationResultItem]
    total: int


# ── Phase 2: Custom Benchmark + AI Rule Creation ──


class CustomBenchmarkCreate(BaseModel):
    """Create a new custom (editable) benchmark."""
    name: str
    version: str = "1.0"
    platform: str = "Windows"
    platform_family: str = "Windows"


class CustomBenchmarkResponse(BaseModel):
    benchmark_id: int
    name: str
    message: str = "Custom benchmark created"


class AIRuleCreateRequest(BaseModel):
    """Create a new rule with AI-generated commands."""
    section_number: str
    title: str
    description: str | None = None
    rationale: str | None = None
    severity: str = "medium"
    profile_applicability: str | None = None
    generate_commands: bool = True


class AIRuleCreateResponse(BaseModel):
    rule_id: int
    section_number: str
    title: str
    commands_generated: bool = False
    message: str = "Rule created"


class BulkGenerateRequest(BaseModel):
    """Request bulk command generation for rules without commands."""
    concurrency: int = 3


class BulkGenerateResponse(BaseModel):
    message: str
    total_rules: int = 0
    commands_generated: int = 0
    status: str = "started"


class BenchmarkExportResponse(BaseModel):
    """Metadata about the exported benchmark."""
    benchmark_name: str
    version: str
    platform: str
    total_rules: int
    total_commands: int
    export_date: str
    message: str = "success"
