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


# ── Phase 3: Rule Testing, Validation, Migration Readiness ──


class RuleTestRequest(BaseModel):
    """Request to test a rule command against a target."""
    target_id: int
    timeout: int = 30


class RuleTestResponse(BaseModel):
    """Result of testing a rule command against a target."""
    rule_id: int
    section_number: str
    audit_command: str
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    expected_output_regex: str | None = None
    match_result: str = "unknown"  # "pass", "fail", "error"
    match_details: str | None = None


class RuleValidateRequest(BaseModel):
    """Mark a rule command as validated after testing."""
    validation_status: str = "validated"  # validated / corrected / flagged
    notes: str | None = None
    corrected_command: str | None = None
    corrected_regex: str | None = None


class MigrationReadinessResponse(BaseModel):
    """Migration readiness stats for a benchmark."""
    benchmark_id: int
    benchmark_name: str
    total_rules: int = 0
    rules_with_commands: int = 0
    rules_validated: int = 0
    rules_generated: int = 0
    rules_no_command: int = 0
    rules_flagged: int = 0
    readiness_percentage: float = 0.0
    status: str = "not_ready"  # not_ready / partial / ready


class ScanComparisonItem(BaseModel):
    """A single rule comparison between two scans."""
    section_number: str
    title: str
    scan_a_status: str | None = None
    scan_b_status: str | None = None
    changed: bool = False
    severity: str | None = None


class ScanComparisonResponse(BaseModel):
    """Comparison of two scans for the same or overlapping benchmarks."""
    scan_a_id: int
    scan_b_id: int
    scan_a_benchmark: str | None = None
    scan_b_benchmark: str | None = None
    scan_a_date: str | None = None
    scan_b_date: str | None = None
    total_rules_compared: int = 0
    rules_improved: int = 0
    rules_regressed: int = 0
    rules_unchanged: int = 0
    rules_new: int = 0
    rules_removed: int = 0
    items: list[ScanComparisonItem] = []
