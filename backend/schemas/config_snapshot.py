from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConfigUpload(BaseModel):
    raw_config: str
    source: str = "upload"


class ConfigSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    scan_id: int | None = None
    source: str
    config_format: str | None = None
    config_hash: str
    device_hostname: str | None = None
    platform_detected: str | None = None
    line_count: int | None = None
    snapshot_at: datetime
    created_at: datetime | None = None


class ConfigSnapshotDetail(ConfigSnapshotResponse):
    raw_config: str


class ConfigCoverageResponse(BaseModel):
    total_rules: int
    answerable: int
    unanswerable: int
    coverage_pct: float
    unanswerable_commands: list[str]


class ConfigDiffResponse(BaseModel):
    snapshot_a_id: int
    snapshot_b_id: int
    unified_diff: str
    lines_added: int
    lines_removed: int


class SecurityFindingResponse(BaseModel):
    check_id: str
    severity: str
    title: str
    description: str
    remediation: str
    matched_lines: list[str]
