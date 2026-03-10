"""Core dataclasses shared across all importers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlatformInfo:
    """Auto-detected platform information from an import source."""

    platform: str = ""              # e.g. "Windows", "Linux", "Cisco"
    platform_family: str = ""       # e.g. "Windows", "Unix", "Network"
    os_version: str = ""            # e.g. "Server 2012 R2", "11 Enterprise"
    benchmark_name: str = ""        # e.g. "CIS Microsoft Windows Server 2012 R2 Benchmark"
    benchmark_version: str = ""     # e.g. "2.6.0"
    profile_level: str = ""         # e.g. "L1", "L2"
    hostname: str = ""              # Target hostname if detectable
    ip_address: str = ""            # Target IP if detectable
    source_tool: str = ""           # e.g. "nessus", "qualys", "native"
    scheme: str = ""                # e.g. "CIS", "NIST", "custom"
    open_ports: list[dict] = field(default_factory=list)  # [{port: int, protocol: str}]

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v}


@dataclass
class ParsedFinding:
    """A single finding parsed from an external report."""

    section_number: str = ""
    title: str = ""
    status: str = ""                # PASS / FAIL / WARNING / ERROR / NOT_APPLICABLE
    severity: str = "medium"

    # The raw values from the source
    actual_value: str = ""
    policy_value: str = ""          # Expected / policy value

    # Rich metadata extracted from description fields
    description: str = ""
    rationale: str = ""
    impact: str = ""
    solution: str = ""
    default_value: str = ""
    see_also: str = ""

    # Framework references parsed from reference codes
    framework_mappings: dict[str, list[str]] = field(default_factory=dict)

    # Source-specific metadata (preserved as-is for audit trail)
    raw_plugin_output: str = ""
    plugin_id: str = ""
    plugin_name: str = ""

    # Internal tracking
    source_row_index: int = -1


@dataclass
class ExtractedRule:
    """A rule specification extracted from a finding for benchmark reconstruction."""

    section_number: str = ""
    title: str = ""
    description: str = ""
    rationale: str = ""
    impact: str = ""
    solution: str = ""              # Maps to remediation_description_raw
    default_value: str = ""
    see_also: str = ""
    severity: str = "medium"
    profile_applicability: str = ""  # e.g. "Level 1 - Member Server"

    # Framework mappings (NIST, HIPAA, CIS Controls, etc.)
    framework_mappings: dict[str, list[str]] = field(default_factory=dict)

    # Expected value (from Nessus "Policy Value")
    expected_value: str = ""

    # Multi-framework support
    framework: str = ""             # e.g. "cis", "stig", "nist", "iso"
    framework_ref: str = ""         # Original ID in source framework (e.g. "V-253283", "AC-2(1)")

    def to_rule_kwargs(self) -> dict[str, Any]:
        """Return kwargs suitable for creating a Rule model instance."""
        import json
        kwargs = {
            "section_number": self.section_number,
            "title": self.title,
            "description": self.description,
            "rationale": self.rationale,
            "default_value": self.default_value,
            "profile_applicability": self.profile_applicability,
            "severity": self.severity,
            "remediation_description_raw": self.solution,
            "audit_description_raw": "",  # No audit command from Nessus
            "references_json": json.dumps(self.framework_mappings) if self.framework_mappings else None,
        }
        if self.framework_ref:
            kwargs["framework_ref"] = self.framework_ref
        return kwargs


@dataclass
class ImportResult:
    """Result summary from a full import operation."""

    scan_id: int = 0
    target_id: int = 0
    target_hostname: str = ""
    benchmark_id: int = 0
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
    migration_readiness: float = 0.0    # Percentage of rules with validated commands

    # Severity enrichment stats
    enrichment_source: str = ""             # Name of preloaded benchmark used for enrichment
    enrichment_source_id: int | None = None # ID of preloaded benchmark used
    rules_enriched: int = 0                 # Total rules enriched (preloaded + AI)
    commands_inherited: int = 0             # Commands copied from preloaded benchmark
    severity_distribution: dict[str, int] = field(default_factory=dict)
    findings_severity_updated: int = 0      # Findings whose severity was synced

    import_record_id: int | None = None

    platform_info: PlatformInfo = field(default_factory=PlatformInfo)

    warnings: list[str] = field(default_factory=list)
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "target_id": self.target_id,
            "target_hostname": self.target_hostname,
            "benchmark_id": self.benchmark_id,
            "benchmark_name": self.benchmark_name,
            "target_created": self.target_created,
            "benchmark_reconstructed": self.benchmark_reconstructed,
            "findings_created": self.findings_created,
            "rules_matched": self.rules_matched,
            "rules_created": self.rules_created,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "not_applicable": self.not_applicable,
            "compliance_percentage": self.compliance_percentage,
            "fp_suspects": self.fp_suspects,
            "migration_readiness": self.migration_readiness,
            "enrichment_source": self.enrichment_source,
            "enrichment_source_id": self.enrichment_source_id,
            "rules_enriched": self.rules_enriched,
            "commands_inherited": self.commands_inherited,
            "severity_distribution": self.severity_distribution,
            "findings_severity_updated": self.findings_severity_updated,
            "import_record_id": self.import_record_id,
            "warnings": self.warnings,
        }
