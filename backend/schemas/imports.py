"""Pydantic schemas for Smart Import API."""

from __future__ import annotations

from pydantic import BaseModel


class SmartImportPreviewResponse(BaseModel):
    """Response from the Smart Import preview endpoint."""

    format: str                                     # nessus_csv, nessus_html, etc.
    filename: str = ""
    platform: str = ""
    platform_family: str = ""
    os_version: str = ""
    benchmark_name: str = ""
    benchmark_version: str = ""
    benchmark_exists: bool = False
    existing_benchmark_id: int | None = None
    existing_benchmark_name: str | None = None
    hostname: str = ""
    ip_address: str = ""
    profile_level: str = ""
    total_findings: int = 0
    total_rules: int = 0
    passed: int = 0
    failed: int = 0
    not_applicable: int = 0
    errors: int = 0
    scheme: str = ""
    source_tool: str = ""
    message: str = ""


class SmartImportResponse(BaseModel):
    """Response from the Smart Import execute endpoint."""

    scan_id: int
    target_id: int
    target_hostname: str = ""
    benchmark_id: int
    benchmark_name: str = ""
    target_created: bool = False
    benchmark_reconstructed: bool = False

    findings_created: int = 0
    rules_matched: int = 0
    rules_created: int = 0

    passed: int = 0
    failed: int = 0
    errors: int = 0
    not_applicable: int = 0
    compliance_percentage: float = 0.0

    fp_suspects: int = 0
    migration_readiness: float = 0.0
    import_record_id: int | None = None

    warnings: list[str] = []
