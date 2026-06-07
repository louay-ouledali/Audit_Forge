"""Nessus CSV parser — transforms Nessus compliance CSV exports into ParsedFindings.

Validated against real data: nessus_report.csv (19,481 lines, 431 rows, 27 columns).

Key columns (0-indexed):
  0: Plugin ID     | 4: Name         | 6: Risk        | 7: Host
  12: Plugin Output | 13: Description | 24: Policy Value | (others flexible)

Plugin IDs for compliance:
  21156 — Windows Compliance Checks
  21157 — Unix Compliance Checks
  33929 — PCI DSS Compliance
  33930 — CIS Compliance

Status mapping:
  PASSED → PASS
  FAILED → FAIL
  WARNING → NOT_APPLICABLE (audit doesn't apply to target)
  ERROR → ERROR

The Description column is the mega-field containing all rule specification data.
Plugin Output is EMPTY for compliance checks.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

from backend.importers.base import ExtractedRule, ParsedFinding, PlatformInfo
from backend.importers.description_parser import (
    extract_profile_level,
    parse_description,
    parse_references,
)

logger = logging.getLogger("auditforge.importers.csv_parser")

# Plugin IDs that indicate compliance check results
COMPLIANCE_PLUGIN_IDS = {"21156", "21157", "33929", "33930"}

# Plugin IDs to skip (scan info, credential checks, port scanners handled separately)
SKIP_PLUGIN_IDS = {"19506", "141118", "10180", "11219", "25220"}

# Plugin IDs that carry port scan data (extracted, not skipped)
PORT_SCAN_PLUGIN_IDS = {"34220"}

# Pattern matching .audit file reference rows (metadata, not real compliance findings)
_AUDIT_FILE_REF_RE = re.compile(r"\.audit\s+from\s+", re.IGNORECASE)

# Status mapping from Nessus vocabulary to AuditForge vocabulary
_STATUS_MAP = {
    "PASSED": "PASS",
    "PASS": "PASS",
    "FAILED": "FAIL",
    "FAIL": "FAIL",
    "WARNING": "NOT_APPLICABLE",
    "ERROR": "ERROR",
}

# Severity mapping from Nessus Risk to AuditForge severity
_SEVERITY_MAP = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "none": "info",
    "": "medium",
}


def detect_nessus_csv(content: str) -> bool:
    """Quick check whether content looks like a Nessus CSV export.

    Looks for characteristic Nessus CSV header columns.
    """
    if not content:
        return False
    # Check first 2000 chars for the header (strip BOM)
    head = content.lstrip("\ufeff\ufffe")[:2000]
    # Nessus CSV always starts with "Plugin ID" column
    return bool(
        re.search(r"Plugin\s*ID", head, re.IGNORECASE)
        and re.search(r"Description", head, re.IGNORECASE)
    )


def parse_nessus_csv(
    content: str,
    *,
    compliance_only: bool = True,
) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a Nessus compliance CSV export.

    Parameters
    ----------
    content : str
        Raw CSV file content.
    compliance_only : bool
        If True (default), only parse compliance plugin rows (21156/21157/etc.).
        If False, also parse vulnerability findings (Phase 4 feature).

    Returns
    -------
    tuple of (findings, platform_info)
        findings: list of ParsedFinding with all extracted data
        platform_info: auto-detected platform information
    """
    if not content or not content.strip():
        raise ValueError("Empty CSV content")

    # Strip BOM (UTF-8-BOM, UTF-16 LE/BE) if present
    content = content.lstrip("\ufeff\ufffe")

    reader = csv.DictReader(io.StringIO(content))

    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    # Validate essential columns exist (case-insensitive matching)
    field_map = _build_field_map(reader.fieldnames)
    _validate_required_fields(field_map)

    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(source_tool="nessus")

    hosts_seen: set[str] = set()
    row_index = 0

    for row in reader:
        row_index += 1
        plugin_id = _get_field(row, field_map, "plugin id", "").strip()

        # Skip non-compliance rows
        if plugin_id in SKIP_PLUGIN_IDS:
            # Extract host info from scan info plugin
            if plugin_id == "19506":
                _extract_scan_info(row, field_map, platform_info)
            continue

        # Extract port scan data (Plugin 34220 = Netstat Portscanner)
        if plugin_id in PORT_SCAN_PLUGIN_IDS:
            _extract_port_data(row, field_map, platform_info)
            continue

        if compliance_only and plugin_id not in COMPLIANCE_PLUGIN_IDS:
            continue

        # Filter out .audit file reference metadata rows (Plugin 21156 rows
        # whose Description is an audit filename, not a real compliance check)
        description_raw = _get_field(row, field_map, "description", "")
        if _AUDIT_FILE_REF_RE.search(description_raw[:200]):
            logger.debug("Row %d: skipped .audit file reference entry", row_index)
            continue

        # Extract host
        host = _get_field(row, field_map, "host", "").strip()
        if host:
            hosts_seen.add(host)
            if not platform_info.ip_address and _looks_like_ip(host):
                platform_info.ip_address = host
            elif not platform_info.hostname and not _looks_like_ip(host):
                platform_info.hostname = host

        # Get the Description mega-field
        if not description_raw.strip():
            logger.debug("Row %d: empty Description, skipping", row_index)
            continue

        # Parse the mega-field
        parsed = parse_description(description_raw)
        if not parsed:
            logger.warning("Row %d: failed to parse Description", row_index)
            continue

        # Determine status from the parsed title line or from CSV Name column
        status = parsed.get("status", "")
        if not status:
            # Try extracting from the Name column (format: "title : [STATUS]")
            name_col = _get_field(row, field_map, "name", "")
            status_match = re.search(r"\[(\w+)\]\s*$", name_col)
            if status_match:
                status = status_match.group(1).upper()

        mapped_status = _STATUS_MAP.get(status.upper(), "MANUAL_REVIEW") if status else "MANUAL_REVIEW"

        # Build section number
        section = parsed.get("section_number", "")
        if not section:
            # Try extracting from Name column
            name_col = _get_field(row, field_map, "name", "")
            sec_match = re.match(r"([\d.]+)\s+", name_col)
            if sec_match:
                section = sec_match.group(1)

        title = parsed.get("title", "")
        if not title:
            title = _get_field(row, field_map, "name", "").strip()
            # Remove status bracket from end
            title = re.sub(r"\s*:\s*\[\w+\]\s*$", "", title)
            # Remove section number from start
            title = re.sub(r"^[\d.]+\s+", "", title)

        # Determine severity
        risk = _get_field(row, field_map, "risk", "").lower()
        severity = _SEVERITY_MAP.get(risk, "medium")
        # For compliance, override to medium if risk is None/empty
        if compliance_only and severity == "info":
            severity = "medium"

        # Build finding
        finding = ParsedFinding(
            section_number=section,
            title=title,
            status=mapped_status,
            severity=severity,
            actual_value=parsed.get("actual_value", ""),
            policy_value=parsed.get("policy_value", ""),
            description=parsed.get("description", ""),
            rationale=parsed.get("rationale", ""),
            impact=parsed.get("impact", ""),
            solution=parsed.get("solution", ""),
            default_value=parsed.get("default_value", ""),
            see_also=parsed.get("see_also", ""),
            framework_mappings=parsed.get("framework_mappings", {}),
            raw_plugin_output=_get_field(row, field_map, "plugin output", ""),
            plugin_id=plugin_id,
            plugin_name=_get_field(row, field_map, "name", ""),
            source_row_index=row_index,
        )

        findings.append(finding)

        # Extract platform info from first compliance finding's Name column
        if not platform_info.benchmark_name:
            name_col = _get_field(row, field_map, "name", "")
            _extract_benchmark_from_name(name_col, platform_info)

        # Extract profile level from framework mappings
        if not platform_info.profile_level and finding.framework_mappings:
            level = extract_profile_level(finding.framework_mappings)
            if level:
                platform_info.profile_level = level

    if not findings:
        raise ValueError("No compliance findings found in CSV. Check that the file contains Nessus compliance scan results.")

    # Set hostname from hosts seen (use IP if only IPs)
    if hosts_seen:
        for h in hosts_seen:
            if not _looks_like_ip(h):
                platform_info.hostname = h
                break
        if not platform_info.hostname:
            platform_info.ip_address = next(iter(hosts_seen))

    logger.info(
        "Parsed %d compliance findings from Nessus CSV (%d hosts: %s, %d open ports)",
        len(findings),
        len(hosts_seen),
        ", ".join(sorted(hosts_seen)[:5]),
        len(platform_info.open_ports),
    )

    return findings, platform_info


def extract_rules_from_findings(findings: list[ParsedFinding]) -> list[ExtractedRule]:
    """Convert parsed findings into extracted rule specifications.

    Used for benchmark reconstruction — creates a rule spec from each unique
    finding (deduplicated by section_number).
    """
    seen_sections: set[str] = set()
    rules: list[ExtractedRule] = []

    for f in findings:
        if not f.section_number or f.section_number in seen_sections:
            continue
        seen_sections.add(f.section_number)

        rule = ExtractedRule(
            section_number=f.section_number,
            title=f.title,
            description=f.description,
            rationale=f.rationale,
            impact=f.impact,
            solution=f.solution,
            default_value=f.default_value,
            see_also=f.see_also,
            severity=f.severity,
            expected_value=f.policy_value,
            framework_mappings=f.framework_mappings,
        )

        # Derive profile from framework mappings
        if f.framework_mappings:
            level = extract_profile_level(f.framework_mappings)
            if level:
                rule.profile_applicability = level

        rules.append(rule)

    logger.info("Extracted %d unique rule specs from %d findings", len(rules), len(findings))
    return rules


# Private helpers


def _build_field_map(fieldnames: list[str]) -> dict[str, str]:
    """Build a case-insensitive field name → actual column name mapping."""
    return {name.strip().lower(): name for name in fieldnames}


def _get_field(row: dict, field_map: dict[str, str], key: str, default: str = "") -> str:
    """Get a field value using case-insensitive key lookup."""
    actual_name = field_map.get(key.lower())
    if actual_name is None:
        return default
    return row.get(actual_name, default) or default


def _validate_required_fields(field_map: dict[str, str]) -> None:
    """Ensure the CSV has the minimum required columns."""
    required = {"plugin id", "description", "name"}
    missing = required - set(field_map.keys())
    if missing:
        raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")


def _looks_like_ip(text: str) -> bool:
    """Check if a string looks like an IP address."""
    return bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", text.strip()))


def _extract_scan_info(row: dict, field_map: dict[str, str], info: PlatformInfo) -> None:
    """Extract platform info from Plugin 19506 (Nessus Scan Information)."""
    output = _get_field(row, field_map, "plugin output", "")
    if not output:
        return

    # Look for OS detection
    os_match = re.search(r"OS\s*:\s*(.+)", output)
    if os_match:
        os_str = os_match.group(1).strip()
        _detect_platform(os_str, info)


def _extract_port_data(row: dict, field_map: dict[str, str], info: PlatformInfo) -> None:
    """Extract open port data from Plugin 34220 (Netstat Portscanner WMI).

    Each row with a non-zero Port value represents a single open port.
    The row with Port=0 is the summary line ("found N open ports") — skip it.
    """
    port_str = _get_field(row, field_map, "port", "0").strip()
    protocol = _get_field(row, field_map, "protocol", "").strip().lower()

    try:
        port_num = int(port_str)
    except (ValueError, TypeError):
        return

    if port_num <= 0:
        return

    # Deduplicate: check if this port+protocol already recorded
    for existing in info.open_ports:
        if existing.get("port") == port_num and existing.get("protocol") == protocol:
            return

    info.open_ports.append({"port": port_num, "protocol": protocol or "tcp"})


def _extract_benchmark_from_name(name: str, info: PlatformInfo) -> None:
    """Extract benchmark name/version/platform from the Nessus "Name" column.

    Typical format:
        "2.2.3 Ensure 'Access this computer ...' (MS only)"
    Or in the compliance_check value (not in Name directly).

    For the actual benchmark name, we look at the audit file path or
    the consistent naming pattern across findings.
    """
    # Try to detect CIS benchmark name pattern from the compliance check plugin name
    cis_match = re.search(
        r"CIS\s+(.*?)\s+Benchmark\s+v?([\d.]+)",
        name,
        re.IGNORECASE,
    )
    if cis_match:
        info.benchmark_name = f"CIS {cis_match.group(1).strip()} Benchmark"
        info.benchmark_version = cis_match.group(2)
        info.scheme = "CIS"
        _detect_platform(cis_match.group(1), info)
        return

    # Try NIST pattern
    nist_match = re.search(r"NIST\s+(.*?)\s+v?([\d.]+)", name, re.IGNORECASE)
    if nist_match:
        info.benchmark_name = f"NIST {nist_match.group(1).strip()}"
        info.benchmark_version = nist_match.group(2)
        info.scheme = "NIST"
        return


def _detect_platform(text: str, info: PlatformInfo) -> None:
    """Detect platform/OS from a text string and populate PlatformInfo."""
    lower = text.lower()

    if "windows" in lower:
        info.platform = "Windows"
        info.platform_family = "Windows"
        # Try to extract version
        ver_match = re.search(
            r"(?:windows\s+)?(server\s+\d{4}(?:\s+r2)?|1[01]|8\.1?)",
            lower,
        )
        if ver_match:
            info.os_version = ver_match.group(1).strip().title()
    elif any(x in lower for x in ("linux", "ubuntu", "centos", "debian", "rhel", "red hat", "suse", "fedora")):
        info.platform = "Linux"
        info.platform_family = "Unix"
    elif any(x in lower for x in ("cisco", "juniper", "fortinet", "palo alto")):
        info.platform = text.split()[0].title()
        info.platform_family = "Network"
    elif any(x in lower for x in ("macos", "apple", "darwin")):
        info.platform = "macOS"
        info.platform_family = "Unix"
    elif any(x in lower for x in ("oracle", "mysql", "postgres", "mssql", "sql server")):
        info.platform = text.split()[0].title()
        info.platform_family = "Database"
