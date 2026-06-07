"""NIST SP 800-53 parser — imports NIST 800-53 control catalogs.

Supports multiple formats:
1. **OSCAL JSON** (official machine-readable format from NIST)
   — ``catalog.groups[].controls[]`` structure
2. **CSV** (spreadsheet exports with Control/Family/Title columns)
3. **XML** (legacy NIST SP 800-53 XML format)

Public API:
- ``detect_nist_json(content)`` → bool
- ``detect_nist_csv(content)`` → bool
- ``detect_nist_xml(content)`` → bool
- ``parse_nist_json(content)`` → (findings, platform_info)
- ``parse_nist_csv(content)`` → (findings, platform_info)
- ``parse_nist_xml(content)`` → (findings, platform_info)
- ``extract_rules_from_nist(findings)`` → list[ExtractedRule]
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import defusedxml.ElementTree as ET

from backend.importers.base import ExtractedRule, ParsedFinding, PlatformInfo

logger = logging.getLogger("auditforge.importers.nist_parser")

# NIST control family prefixes for detection
_NIST_FAMILY_IDS = {
    "AC", "AT", "AU", "CA", "CM", "CP", "IA", "IR", "MA", "MP",
    "PE", "PL", "PM", "PS", "PT", "RA", "SA", "SC", "SI", "SR",
}

# Baseline impact levels
_BASELINES = {"LOW", "MODERATE", "HIGH"}

# Priority → severity mapping
_PRIORITY_MAP = {
    "P1": "high",
    "P2": "medium",
    "P3": "low",
    "P0": "critical",
}


#  Format detection

def detect_nist_json(content: str) -> bool:
    """Return True if content looks like a NIST OSCAL JSON catalog."""
    stripped = content.strip()
    if not stripped.startswith("{"):
        return False
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return False

    # OSCAL catalog format
    if "catalog" in data and "groups" in data.get("catalog", {}):
        return True
    # Look for NIST control patterns in top-level keys
    if "controls" in data or "control-families" in data:
        return True
    return False


def detect_nist_csv(content: str) -> bool:
    """Return True if content looks like a NIST 800-53 CSV export."""
    first_lines = content[:2000].lower()
    # Check for NIST-specific column headers
    nist_headers = ["control identifier", "control name", "control family"]
    alt_headers = ["control id", "family", "title", "baseline"]
    return (
        any(h in first_lines for h in nist_headers)
        or (
            sum(1 for h in alt_headers if h in first_lines) >= 2
            and _has_nist_control_ids(content[:3000])
        )
    )


def detect_nist_xml(content: str) -> bool:
    """Return True if content looks like a NIST 800-53 XML file."""
    if not content.strip().startswith("<"):
        return False
    return bool(
        re.search(r"<controls:control", content[:2000])
        or (
            re.search(r"800-53|SP800-53", content[:3000])
            and re.search(r"<(?:control|family|statement)", content[:3000])
        )
    )


def _has_nist_control_ids(text: str) -> bool:
    """Check if text contains NIST-style control identifiers (AC-1, AU-3, etc.)."""
    matches = re.findall(r"\b[A-Z]{2}-\d{1,2}(?:\(\d+\))?\b", text)
    if len(matches) < 3:
        return False
    families = {m[:2] for m in matches}
    return bool(families & _NIST_FAMILY_IDS)


#  OSCAL JSON parsing

def parse_nist_json(content: str) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a NIST OSCAL JSON catalog file."""
    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(
        source_tool="nist_oscal",
        scheme="NIST",
        benchmark_name="NIST SP 800-53 Rev 5",
    )

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse NIST JSON: %s", exc)
        return findings, platform_info

    catalog = data.get("catalog", data)

    # Extract metadata
    metadata = catalog.get("metadata", {})
    if metadata.get("title"):
        platform_info.benchmark_name = metadata["title"]
    if metadata.get("version"):
        platform_info.benchmark_version = metadata["version"]

    # Parse groups → controls
    idx = 0
    for group in catalog.get("groups", []):
        family_id = group.get("id", "").upper()
        family_title = group.get("title", "")

        for control in group.get("controls", []):
            finding = _parse_oscal_control(control, family_id, family_title, idx)
            findings.append(finding)
            idx += 1

            # Parse control enhancements
            for enhancement in control.get("controls", []):
                finding = _parse_oscal_control(enhancement, family_id, family_title, idx)
                findings.append(finding)
                idx += 1

    logger.info(
        "Parsed NIST OSCAL JSON: %d controls from '%s'",
        len(findings), platform_info.benchmark_name,
    )

    return findings, platform_info


def _parse_oscal_control(
    control: dict,
    family_id: str,
    family_title: str,
    idx: int,
) -> ParsedFinding:
    """Parse a single OSCAL control into a ParsedFinding."""
    control_id = control.get("id", "").upper()
    title = control.get("title", "")

    # Build description from parts/prose
    description_parts: list[str] = []
    for part in control.get("parts", []):
        prose = part.get("prose", "")
        if prose:
            part_name = part.get("name", "")
            if part_name and part_name != "statement":
                description_parts.append(f"[{part_name}] {prose}")
            else:
                description_parts.append(prose)

    description = "\n".join(description_parts)

    # Extract properties (baseline, priority)
    props = {p.get("name"): p.get("value") for p in control.get("props", [])}
    priority = props.get("priority", "P2")
    severity = _PRIORITY_MAP.get(priority, "medium")

    # Build framework references
    refs: dict[str, list[str]] = {"NIST_800_53": [control_id]}
    if family_id:
        refs["NIST_FAMILY"] = [f"{family_id} - {family_title}"]

    return ParsedFinding(
        section_number=control_id,
        title=f"{control_id}: {title}" if title else control_id,
        status="NOT_APPLICABLE",  # Catalog only — no scan results
        severity=severity,
        description=description,
        framework_mappings=refs,
        source_row_index=idx,
    )


#  CSV parsing

def parse_nist_csv(content: str) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a NIST 800-53 CSV export."""
    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(
        source_tool="nist_csv",
        scheme="NIST",
        benchmark_name="NIST SP 800-53",
    )

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return findings, platform_info

    # Normalize column names
    col_map = _build_column_map(reader.fieldnames)

    idx = 0
    for row in reader:
        control_id = _get_col(row, col_map, "control_id", "").strip().upper()
        if not control_id or not re.match(r"[A-Z]{2}-\d", control_id):
            continue

        title = _get_col(row, col_map, "title", "")
        family = _get_col(row, col_map, "family", "")
        description = _get_col(row, col_map, "description", "")
        baseline = _get_col(row, col_map, "baseline", "")
        priority = _get_col(row, col_map, "priority", "P2")

        severity = _PRIORITY_MAP.get(priority.strip(), "medium")

        refs: dict[str, list[str]] = {"NIST_800_53": [control_id]}
        if family:
            refs["NIST_FAMILY"] = [family]
        if baseline:
            refs["BASELINE"] = [baseline]

        finding = ParsedFinding(
            section_number=control_id,
            title=f"{control_id}: {title}" if title else control_id,
            status="NOT_APPLICABLE",
            severity=severity,
            description=description,
            framework_mappings=refs,
            source_row_index=idx,
        )
        findings.append(finding)
        idx += 1

    logger.info("Parsed NIST CSV: %d controls", len(findings))
    return findings, platform_info


#  XML parsing

def parse_nist_xml(content: str) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a NIST 800-53 XML file."""
    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(
        source_tool="nist_xml",
        scheme="NIST",
        benchmark_name="NIST SP 800-53",
    )

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        logger.error("Failed to parse NIST XML: %s", exc)
        return findings, platform_info

    # Determine namespace
    ns_uri = ""
    if "}" in root.tag:
        ns_uri = root.tag.split("}")[0] + "}"

    idx = 0
    for control_el in root.iter(f"{ns_uri}control" if ns_uri else "control"):
        number = ""
        title = ""
        description = ""

        num_el = control_el.find(f"{ns_uri}number" if ns_uri else "number")
        if num_el is not None and num_el.text:
            number = num_el.text.strip().upper()

        title_el = control_el.find(f"{ns_uri}title" if ns_uri else "title")
        if title_el is not None and title_el.text:
            title = title_el.text.strip()

        stmt_el = control_el.find(f"{ns_uri}statement" if ns_uri else "statement")
        if stmt_el is not None:
            desc_el = stmt_el.find(f"{ns_uri}description" if ns_uri else "description")
            if desc_el is not None and desc_el.text:
                description = desc_el.text.strip()

        if not number:
            continue

        refs: dict[str, list[str]] = {"NIST_800_53": [number]}

        finding = ParsedFinding(
            section_number=number,
            title=f"{number}: {title}" if title else number,
            status="NOT_APPLICABLE",
            severity="medium",
            description=description,
            framework_mappings=refs,
            source_row_index=idx,
        )
        findings.append(finding)
        idx += 1

    logger.info("Parsed NIST XML: %d controls", len(findings))
    return findings, platform_info


#  Rule extraction

def extract_rules_from_nist(findings: list[ParsedFinding]) -> list[ExtractedRule]:
    """Convert NIST ParsedFindings into ExtractedRule objects."""
    rules: list[ExtractedRule] = []
    for f in findings:
        rule = ExtractedRule(
            section_number=f.section_number,
            title=f.title,
            description=f.description,
            severity=f.severity,
            solution=f.solution,
            framework_mappings=f.framework_mappings,
            framework="nist",
            framework_ref=f.section_number,  # NIST control ID like AC-2(1)
        )
        rules.append(rule)
    return rules


#  Helpers

def _build_column_map(fieldnames: list[str]) -> dict[str, str]:
    """Build a normalized column name → actual column name mapping."""
    col_map: dict[str, str] = {}
    for name in fieldnames:
        lower = name.lower().strip()
        if "control" in lower and ("id" in lower or "identifier" in lower or "number" in lower):
            col_map["control_id"] = name
        elif lower in ("title", "control name", "control_name"):
            col_map["title"] = name
        elif "family" in lower:
            col_map["family"] = name
        elif "description" in lower or "supplemental" in lower:
            col_map["description"] = name
        elif "baseline" in lower or "impact" in lower:
            col_map["baseline"] = name
        elif "priority" in lower:
            col_map["priority"] = name
    return col_map


def _get_col(row: dict, col_map: dict[str, str], key: str, default: str = "") -> str:
    """Get a column value using the normalized mapping."""
    actual_name = col_map.get(key)
    if actual_name and actual_name in row:
        return row[actual_name] or default
    return default
