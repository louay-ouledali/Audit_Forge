"""Generic XCCDF/SCAP parser — imports any XCCDF 1.1/1.2 benchmark XML.

Handles non-STIG XCCDF files that follow the standard SCAP data stream
format (e.g., OpenSCAP exports, OVAL results, generic XCCDF benchmarks).

DISA STIGs use XCCDF but have their own specific structure handled by
``stig_parser.py``. This parser is the fallback for other XCCDF files.

Public API:
- ``detect_xccdf(content)`` → bool
- ``parse_xccdf(content)`` → (findings, platform_info)
- ``extract_rules_from_xccdf(findings)`` → list[ExtractedRule]
"""

from __future__ import annotations

import logging
import re
import defusedxml.ElementTree as ET

from backend.importers.base import ExtractedRule, ParsedFinding, PlatformInfo

logger = logging.getLogger("auditforge.importers.xccdf_parser")

# Known XCCDF namespace URIs
_XCCDF_NAMESPACES = [
    "http://checklists.nist.gov/xccdf/1.2",
    "http://checklists.nist.gov/xccdf/1.1",
]

# Severity mapping
_SEVERITY_MAP = {
    "high": "high",
    "medium": "medium",
    "low": "low",
    "unknown": "medium",
    "info": "informational",
    "informational": "informational",
}

# XCCDF result mapping
_RESULT_MAP = {
    "pass": "PASS",
    "fail": "FAIL",
    "error": "ERROR",
    "unknown": "ERROR",
    "notapplicable": "NOT_APPLICABLE",
    "notchecked": "NOT_APPLICABLE",
    "notselected": "NOT_APPLICABLE",
    "informational": "PASS",
    "fixed": "PASS",
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Format detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_xccdf(content: str) -> bool:
    """Return True if content is a non-STIG XCCDF file.

    Returns False for DISA STIG files (those are handled by stig_parser).
    """
    if not content or not content.strip().startswith("<"):
        return False

    head = content[:3000]

    # Must have XCCDF indicators
    has_xccdf = bool(
        re.search(r"checklists\.nist\.gov/xccdf", head)
        or re.search(r"<(?:\w+:)?Benchmark\b", head)
    )

    if not has_xccdf:
        return False

    # Exclude DISA STIGs (handled by stig_parser)
    is_stig = bool(
        re.search(r"STIG|Security Technical Implementation Guide", head, re.IGNORECASE)
        and re.search(r"DISA|Defense Information Systems Agency", content[:5000], re.IGNORECASE)
    )

    return not is_stig


# ═══════════════════════════════════════════════════════════════════════════════
#  XCCDF parsing
# ═══════════════════════════════════════════════════════════════════════════════

def parse_xccdf(content: str) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a generic XCCDF benchmark XML file.

    Returns a list of ParsedFinding (one per Rule) and platform info.
    Handles both XCCDF 1.1 and 1.2 schemas.
    """
    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(source_tool="xccdf", scheme="SCAP")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        logger.error("Failed to parse XCCDF XML: %s", exc)
        return findings, platform_info

    # Determine namespace
    ns_uri = ""
    root_tag = root.tag
    if "}" in root_tag:
        ns_uri = root_tag.split("}")[0] + "}"

    # Extract benchmark metadata
    title_el = root.find(f"{ns_uri}title") if ns_uri else root.find("title")
    if title_el is not None and title_el.text:
        platform_info.benchmark_name = title_el.text.strip()
        _detect_xccdf_platform(title_el.text, platform_info)

    version_el = root.find(f"{ns_uri}version") if ns_uri else root.find("version")
    if version_el is not None and version_el.text:
        platform_info.benchmark_version = version_el.text.strip()

    # Detect scheme from description/title
    desc_el = root.find(f"{ns_uri}description") if ns_uri else root.find("description")
    if desc_el is not None and desc_el.text:
        _detect_scheme(desc_el.text, platform_info)

    # Check for TestResult (XCCDF results file) vs Benchmark (definition file)
    test_results = list(root.iter(f"{ns_uri}TestResult" if ns_uri else "TestResult"))
    has_results = len(test_results) > 0

    # Build rule-result map from TestResult if available
    result_map: dict[str, str] = {}
    if has_results:
        for test_result in test_results:
            for rule_result in test_result.iter(f"{ns_uri}rule-result" if ns_uri else "rule-result"):
                rule_id = rule_result.get("idref", "")
                result_el = rule_result.find(f"{ns_uri}result" if ns_uri else "result")
                if rule_id and result_el is not None and result_el.text:
                    result_map[rule_id] = result_el.text.strip().lower()

    # Iterate over Groups → Rules
    idx = 0
    for group in root.iter(f"{ns_uri}Group" if ns_uri else "Group"):
        group_id = group.get("id", "")
        group_title = ""
        group_title_el = group.find(f"{ns_uri}title" if ns_uri else "title")
        if group_title_el is not None and group_title_el.text:
            group_title = group_title_el.text.strip()

        for rule_elem in group.iter(f"{ns_uri}Rule" if ns_uri else "Rule"):
            rule_id = rule_elem.get("id", "")
            severity = _SEVERITY_MAP.get(rule_elem.get("severity", "medium"), "medium")

            title = ""
            title_el_r = rule_elem.find(f"{ns_uri}title" if ns_uri else "title")
            if title_el_r is not None and title_el_r.text:
                title = title_el_r.text.strip()

            description = ""
            desc_el_r = rule_elem.find(f"{ns_uri}description" if ns_uri else "description")
            if desc_el_r is not None and desc_el_r.text:
                description = _clean_html(desc_el_r.text)

            fix_text = ""
            fix_el = rule_elem.find(f"{ns_uri}fixtext" if ns_uri else "fixtext")
            if fix_el is not None and fix_el.text:
                fix_text = fix_el.text.strip()

            rationale = ""
            rat_el = rule_elem.find(f"{ns_uri}rationale" if ns_uri else "rationale")
            if rat_el is not None and rat_el.text:
                rationale = rat_el.text.strip()

            # Check for result
            status = "NOT_APPLICABLE"
            if rule_id in result_map:
                status = _RESULT_MAP.get(result_map[rule_id], "ERROR")

            # Extract references
            refs: dict[str, list[str]] = {}
            for ident_el in rule_elem.iter(f"{ns_uri}ident" if ns_uri else "ident"):
                if ident_el.text:
                    ident = ident_el.text.strip()
                    if ident.startswith("CCE-"):
                        refs.setdefault("CCE", []).append(ident)
                    elif ident.startswith("CCI-"):
                        refs.setdefault("CCI", []).append(ident)
                    else:
                        refs.setdefault("OTHER", []).append(ident)

            # Use group_id as section number for consistent identification
            section = _extract_section_number(group_id, rule_id, idx)

            finding = ParsedFinding(
                section_number=section,
                title=title or f"{section} - {group_title}",
                status=status,
                severity=severity,
                description=description,
                rationale=rationale,
                solution=fix_text,
                framework_mappings=refs,
                source_row_index=idx,
            )
            findings.append(finding)
            idx += 1

    # If no Groups found, look for standalone Rules
    if not findings:
        for rule_elem in root.iter(f"{ns_uri}Rule" if ns_uri else "Rule"):
            rule_id = rule_elem.get("id", "")
            severity = _SEVERITY_MAP.get(rule_elem.get("severity", "medium"), "medium")

            title = ""
            title_el_r = rule_elem.find(f"{ns_uri}title" if ns_uri else "title")
            if title_el_r is not None and title_el_r.text:
                title = title_el_r.text.strip()

            description = ""
            desc_el_r = rule_elem.find(f"{ns_uri}description" if ns_uri else "description")
            if desc_el_r is not None and desc_el_r.text:
                description = _clean_html(desc_el_r.text)

            status = "NOT_APPLICABLE"
            if rule_id in result_map:
                status = _RESULT_MAP.get(result_map[rule_id], "ERROR")

            section = _extract_section_number("", rule_id, idx)

            finding = ParsedFinding(
                section_number=section,
                title=title,
                status=status,
                severity=severity,
                description=description,
                source_row_index=idx,
            )
            findings.append(finding)
            idx += 1

    logger.info(
        "Parsed XCCDF: %d rules from '%s' v%s (has_results=%s)",
        len(findings),
        platform_info.benchmark_name,
        platform_info.benchmark_version,
        has_results,
    )

    return findings, platform_info


# ═══════════════════════════════════════════════════════════════════════════════
#  Rule extraction
# ═══════════════════════════════════════════════════════════════════════════════

def extract_rules_from_xccdf(findings: list[ParsedFinding]) -> list[ExtractedRule]:
    """Convert XCCDF ParsedFindings into ExtractedRule objects."""
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
            framework="xccdf",
            framework_ref=f.section_number,
        )
        rules.append(rule)
    return rules


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_html(text: str) -> str:
    """Remove basic HTML tags from XCCDF description content."""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _extract_section_number(group_id: str, rule_id: str, fallback_idx: int) -> str:
    """Extract a meaningful section number from XCCDF identifiers."""
    # Try V-ID pattern
    for ident in (group_id, rule_id):
        m = re.search(r"(V-\d+)", ident)
        if m:
            return m.group(1)

    # Try numeric section from group id (e.g., "xccdf_..._group_1.1.1")
    for ident in (group_id, rule_id):
        m = re.search(r"(\d+(?:\.\d+)+)", ident)
        if m:
            return m.group(1)

    # Try rule suffix (e.g., "xccdf_..._rule_configure_ssh_idle")
    if rule_id:
        parts = rule_id.split("_rule_")
        if len(parts) > 1:
            return parts[-1][:60]

    return f"XCCDF-{fallback_idx}"


def _detect_xccdf_platform(title: str, info: PlatformInfo) -> None:
    """Detect platform from XCCDF benchmark title."""
    lower = title.lower()

    if "windows" in lower:
        info.platform = "Windows Server" if "server" in lower else "Windows"
        info.platform_family = "windows"
    elif any(x in lower for x in ("rhel", "red hat")):
        info.platform = "Red Hat"
        info.platform_family = "linux"
    elif "ubuntu" in lower:
        info.platform = "Ubuntu"
        info.platform_family = "linux"
    elif "debian" in lower:
        info.platform = "Debian"
        info.platform_family = "linux"
    elif "suse" in lower or "sles" in lower:
        info.platform = "SUSE"
        info.platform_family = "linux"
    elif "centos" in lower:
        info.platform = "CentOS"
        info.platform_family = "linux"
    elif "oracle linux" in lower:
        info.platform = "Oracle Linux"
        info.platform_family = "linux"
    elif "linux" in lower or "unix" in lower:
        info.platform = "Linux"
        info.platform_family = "linux"
    elif "cisco" in lower:
        info.platform = "Cisco"
        info.platform_family = "network"


def _detect_scheme(text: str, info: PlatformInfo) -> None:
    """Detect framework scheme from description text."""
    lower = text.lower()
    if "cis" in lower and "benchmark" in lower:
        info.scheme = "CIS"
    elif "nist" in lower:
        info.scheme = "NIST"
    elif "disa" in lower or "stig" in lower:
        info.scheme = "STIG"
