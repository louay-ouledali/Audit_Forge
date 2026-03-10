"""ISO 27001/27002 parser — imports ISO 27001 Annex A controls.

Supports:
1. **JSON** — structured export of ISO 27001:2022 Annex A controls
2. **CSV** — spreadsheet exports with Control/Clause/Domain columns

ISO 27001:2022 reorganised controls into 4 themes (Organisational, People,
Physical, Technological) with 93 controls. ISO 27002:2022 provides detailed
guidance for each.

Public API:
- ``detect_iso_json(content)`` → bool
- ``detect_iso_csv(content)`` → bool
- ``parse_iso_json(content)`` → (findings, platform_info)
- ``parse_iso_csv(content)`` → (findings, platform_info)
- ``extract_rules_from_iso(findings)`` → list[ExtractedRule]
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re

from backend.importers.base import ExtractedRule, ParsedFinding, PlatformInfo

logger = logging.getLogger("auditforge.importers.iso_parser")

# ISO 27001:2022 Annex A control numbering pattern: A.5.1, A.8.24, etc.
_ISO_CONTROL_PATTERN = re.compile(r"(?:A\.)?([5-8])\.\d{1,2}")

# Theme domains in ISO 27001:2022
_ISO_THEMES = {
    "5": "Organisational Controls",
    "6": "People Controls",
    "7": "Physical Controls",
    "8": "Technological Controls",
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Format detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_iso_json(content: str) -> bool:
    """Return True if content looks like an ISO 27001 JSON export."""
    stripped = content.strip()
    if not stripped.startswith("{") and not stripped.startswith("["):
        return False
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return False

    # Check for ISO indicators
    if isinstance(data, dict):
        text_repr = json.dumps(data)[:3000].lower()
        return (
            ("27001" in text_repr or "27002" in text_repr)
            and ("annex" in text_repr or "control" in text_repr)
        )
    if isinstance(data, list) and data:
        first = data[0] if isinstance(data[0], dict) else {}
        keys_lower = {k.lower() for k in first}
        return bool(
            {"control", "clause"} & keys_lower
            or {"control_id", "domain"} & keys_lower
        ) and _has_iso_control_ids(json.dumps(data[:5])[:1000])

    return False


def detect_iso_csv(content: str) -> bool:
    """Return True if content looks like an ISO 27001 CSV export."""
    first_lines = content[:2000].lower()
    iso_headers = ["annex", "clause", "control objective", "27001", "27002"]
    control_headers = ["control id", "control name", "domain", "theme"]
    matches = sum(1 for h in iso_headers + control_headers if h in first_lines)
    return matches >= 2 and _has_iso_control_ids(content[:3000])


def _has_iso_control_ids(text: str) -> bool:
    """Check if text contains ISO-style control identifiers (A.5.1, 8.24, etc.)."""
    matches = re.findall(r"\bA?\.[5-8]\.\d{1,2}\b", text)
    return len(matches) >= 3


# ═══════════════════════════════════════════════════════════════════════════════
#  JSON parsing
# ═══════════════════════════════════════════════════════════════════════════════

def parse_iso_json(content: str) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse an ISO 27001 JSON control catalog."""
    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(
        source_tool="iso_json",
        scheme="ISO",
        benchmark_name="ISO 27001:2022",
    )

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse ISO JSON: %s", exc)
        return findings, platform_info

    controls: list[dict] = []
    if isinstance(data, list):
        controls = data
    elif isinstance(data, dict):
        # Could be {metadata: {...}, controls: [...]} or {annex_a: [...]}
        if "metadata" in data:
            meta = data["metadata"]
            if meta.get("title"):
                platform_info.benchmark_name = meta["title"]
            if meta.get("version"):
                platform_info.benchmark_version = meta["version"]
        controls = (
            data.get("controls", [])
            or data.get("annex_a", [])
            or data.get("requirements", [])
        )

    idx = 0
    for ctrl in controls:
        if not isinstance(ctrl, dict):
            continue

        control_id = (
            ctrl.get("control_id", "")
            or ctrl.get("clause", "")
            or ctrl.get("id", "")
        ).strip()
        if not control_id:
            continue

        # Normalise to "A.X.Y" format
        if not control_id.startswith("A."):
            if re.match(r"[5-8]\.\d", control_id):
                control_id = f"A.{control_id}"

        title = ctrl.get("title", "") or ctrl.get("control_name", "") or ctrl.get("name", "")
        description = ctrl.get("description", "") or ctrl.get("guidance", "")
        domain = ctrl.get("domain", "") or ctrl.get("theme", "") or ctrl.get("category", "")
        purpose = ctrl.get("purpose", "") or ctrl.get("objective", "")

        refs: dict[str, list[str]] = {"ISO_27001": [control_id]}
        if domain:
            refs["ISO_DOMAIN"] = [domain]

        finding = ParsedFinding(
            section_number=control_id,
            title=f"{control_id}: {title}" if title else control_id,
            status="NOT_APPLICABLE",
            severity="medium",
            description=description,
            rationale=purpose,
            framework_mappings=refs,
            source_row_index=idx,
        )
        findings.append(finding)
        idx += 1

    logger.info(
        "Parsed ISO JSON: %d controls from '%s'",
        len(findings), platform_info.benchmark_name,
    )
    return findings, platform_info


# ═══════════════════════════════════════════════════════════════════════════════
#  CSV parsing
# ═══════════════════════════════════════════════════════════════════════════════

def parse_iso_csv(content: str) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse an ISO 27001 CSV export."""
    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(
        source_tool="iso_csv",
        scheme="ISO",
        benchmark_name="ISO 27001:2022",
    )

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return findings, platform_info

    col_map = _build_column_map(reader.fieldnames)

    idx = 0
    for row in reader:
        control_id = _get_col(row, col_map, "control_id", "").strip()
        if not control_id:
            continue

        if not control_id.startswith("A."):
            if re.match(r"[5-8]\.\d", control_id):
                control_id = f"A.{control_id}"

        title = _get_col(row, col_map, "title", "")
        description = _get_col(row, col_map, "description", "")
        domain = _get_col(row, col_map, "domain", "")

        refs: dict[str, list[str]] = {"ISO_27001": [control_id]}
        if domain:
            refs["ISO_DOMAIN"] = [domain]

        finding = ParsedFinding(
            section_number=control_id,
            title=f"{control_id}: {title}" if title else control_id,
            status="NOT_APPLICABLE",
            severity="medium",
            description=description,
            framework_mappings=refs,
            source_row_index=idx,
        )
        findings.append(finding)
        idx += 1

    logger.info("Parsed ISO CSV: %d controls", len(findings))
    return findings, platform_info


# ═══════════════════════════════════════════════════════════════════════════════
#  Rule extraction
# ═══════════════════════════════════════════════════════════════════════════════

def extract_rules_from_iso(findings: list[ParsedFinding]) -> list[ExtractedRule]:
    """Convert ISO ParsedFindings into ExtractedRule objects."""
    rules: list[ExtractedRule] = []
    for f in findings:
        rule = ExtractedRule(
            section_number=f.section_number,
            title=f.title,
            description=f.description,
            rationale=f.rationale,
            severity=f.severity,
            solution=f.solution,
            framework_mappings=f.framework_mappings,
            framework="iso",
            framework_ref=f.section_number,  # ISO control ID like A.5.1
        )
        rules.append(rule)
    return rules


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _build_column_map(fieldnames: list[str]) -> dict[str, str]:
    """Build a normalized column name → actual column name mapping."""
    col_map: dict[str, str] = {}
    for name in fieldnames:
        lower = name.lower().strip()
        if "control" in lower and ("id" in lower or "number" in lower or "clause" in lower):
            col_map["control_id"] = name
        elif lower in ("clause", "section", "annex"):
            col_map.setdefault("control_id", name)
        elif lower in ("title", "control name", "control_name", "name"):
            col_map["title"] = name
        elif "domain" in lower or "theme" in lower or "category" in lower:
            col_map["domain"] = name
        elif "description" in lower or "guidance" in lower:
            col_map["description"] = name
    return col_map


def _get_col(row: dict, col_map: dict[str, str], key: str, default: str = "") -> str:
    """Get a column value using the normalized mapping."""
    actual_name = col_map.get(key)
    if actual_name and actual_name in row:
        return row[actual_name] or default
    return default
