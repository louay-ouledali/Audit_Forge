from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GenerateScriptRequest(BaseModel):
    """Request body for POST /api/scans/generate-script and preview."""

    target_id: int | None = None
    benchmark_id: int
    mission_id: int | None = None
    preset_id: int | None = None
    selected_rule_ids: list[int] | None = None
    category_filter: list[str] | None = None
    severity_filter: list[str] | None = None
    profile_filter: str | None = None


class ScriptPreviewRule(BaseModel):
    id: int
    section_number: str
    title: str | None = None
    severity: str | None = None


class ScriptPreviewResponse(BaseModel):
    total_rules: int
    rules: list[ScriptPreviewRule]


# ── Network Scan ──────────────────────────────────────────────


class NetworkScanRequest(BaseModel):
    """Request body for POST /api/scans/network."""

    target_id: int
    benchmark_id: int
    mission_id: int | None = None
    preset_id: int | None = None
    selected_rule_ids: list[int] | None = None
    category_filter: list[str] | None = None
    severity_filter: list[str] | None = None
    profile_filter: str | None = None


class NetworkScanResponse(BaseModel):
    scan_id: int
    status: str


class ScanStatusResponse(BaseModel):
    scan_id: int
    status: str
    progress: int = 0
    total: int = 0
    current_rule: str = ""
    passed: int = 0
    failed: int = 0
    errors: int = 0
    compliance_percentage: float = 0.0
    error_message: str | None = None


class ScanCancelResponse(BaseModel):
    scan_id: int
    status: str
    message: str


# ── Scan Batch ("Scan All") ──────────────────────────────────


class ScanBatchRequest(BaseModel):
    """Request body for POST /api/scans/batch."""

    mission_id: int
    target_ids: list[int] | None = None        # None = all mission targets
    benchmark_overrides: dict[str, int] | None = None  # target_id (str) → benchmark_id
    skip_untestable: bool = True
    concurrency: int = 3


class ScanBatchItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    target_hostname: str | None = None
    target_ip: str | None = None
    benchmark_id: int | None = None
    benchmark_name: str | None = None
    scan_id: int | None = None
    status: str
    skip_reason: str | None = None
    error_message: str | None = None


class ScanBatchResponse(BaseModel):
    batch_id: int
    status: str
    total_targets: int
    scannable: int
    skipped: int
    items: list[ScanBatchItemResponse]


class ScanBatchStatusResponse(BaseModel):
    batch_id: int
    status: str
    total_targets: int
    completed_targets: int
    failed_targets: int
    skipped_targets: int
    items: list[ScanBatchItemResponse]
