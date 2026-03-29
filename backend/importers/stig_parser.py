"""DISA STIG XCCDF parser — imports STIG checklist XML files.

Supports two formats:
1. XCCDF 1.2 (DISA STIG Benchmark XML) — ``<Benchmark>`` root with
   ``<Group>`` → ``<Rule>`` hierarchy
2. STIG Viewer .ckl (Checklist) — ``<CHECKLIST>`` root with
   ``<VULN>`` elements containing ``<STIG_DATA>`` attributes

Both formats are produced by DISA and used extensively by DoD/federal
auditors.

Public API:
- ``detect_stig_xccdf(content)`` → bool
- ``detect_stig_ckl(content)`` → bool
- ``parse_stig_xccdf(content)`` → (findings, platform_info)
- ``parse_stig_ckl(content)`` → (findings, platform_info)
- ``extract_rules_from_stig(findings)`` → list[ExtractedRule]
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

from backend.importers.base import ExtractedRule, ParsedFinding, PlatformInfo

logger = logging.getLogger("auditforge.importers.stig_parser")

# XCCDF namespaces used by DISA STIGs
_XCCDF_NS = {
    "xccdf": "http://checklists.nist.gov/xccdf/1.2",
    "xccdf11": "http://checklists.nist.gov/xccdf/1.1",
    "dc": "http://purl.org/dc/elements/1.1/",
}

# Severity mapping from XCCDF/STIG to AuditForge
_SEVERITY_MAP = {
    "high": "high",
    "medium": "medium",
    "low": "low",
    "unknown": "medium",
    "CAT I": "high",
    "CAT II": "medium",
    "CAT III": "low",
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Format detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_stig_xccdf(content: str) -> bool:
    """Return True if content looks like a DISA STIG XCCDF XML file."""
    if not content or not content.strip().startswith("<?xml") and not content.strip().startswith("<"):
        return False
    # Look for XCCDF Benchmark root element with STIG indicators
    return bool(
        re.search(r"<(?:\w+:)?Benchmark\b", content[:2000])
        and (
            re.search(r"checklists\.nist\.gov/xccdf", content[:2000])
            or re.search(r"STIG|Security Technical Implementation Guide", content[:5000], re.IGNORECASE)
        )
    )


def detect_stig_ckl(content: str) -> bool:
    """Return True if content looks like a STIG Viewer .ckl checklist."""
    if not content or not content.strip().startswith("<?xml") and not content.strip().startswith("<"):
        return False
    return bool(re.search(r"<CHECKLIST>", content[:500]))


# ═══════════════════════════════════════════════════════════════════════════════
#  XCCDF parsing
# ═══════════════════════════════════════════════════════════════════════════════

def _find_text(elem: ET.Element, tag: str, ns: dict[str, str], default: str = "") -> str:
    """Find text content of a child element, trying multiple namespace prefixes."""
    for prefix in ("xccdf", "xccdf11", ""):
        if prefix:
            path = f"{prefix}:{tag}"
            child = elem.find(path, ns)
        else:
            child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
    return default


def _get_severity(elem: ET.Element) -> str:
    """Extract severity from XCCDF Rule element attributes."""
    sev = elem.get("severity", "medium")
    return _SEVERITY_MAP.get(sev, "medium")


def parse_stig_xccdf(content: str) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a DISA STIG XCCDF Benchmark XML file.

    Returns a list of ParsedFinding (one per Rule) and platform info.
    """
    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(source_tool="stig_xccdf", scheme="STIG")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        logger.error("Failed to parse STIG XCCDF XML: %s", exc)
        return findings, platform_info

    # Determine namespace
    ns_uri = ""
    root_tag = root.tag
    if "}" in root_tag:
        ns_uri = root_tag.split("}")[0] + "}"

    # Extract benchmark title/version
    title_elem = root.find(f"{ns_uri}title") if ns_uri else root.find("title")
    if title_elem is not None and title_elem.text:
        platform_info.benchmark_name = title_elem.text.strip()
        _detect_stig_platform(title_elem.text, platform_info)

    version_elem = root.find(f"{ns_uri}version") if ns_uri else root.find("version")
    if version_elem is not None and version_elem.text:
        platform_info.benchmark_version = version_elem.text.strip()

    # Iterate over Group → Rule
    idx = 0
    for group in root.iter(f"{ns_uri}Group" if ns_uri else "Group"):
        group_id = group.get("id", "")

        for rule_elem in group.iter(f"{ns_uri}Rule" if ns_uri else "Rule"):
            rule_id = rule_elem.get("id", "")
            severity = _get_severity(rule_elem)

            # Extract V-ID from group_id or rule_id
            v_id = _extract_vuln_id(group_id) or _extract_vuln_id(rule_id)

            title = ""
            title_el = rule_elem.find(f"{ns_uri}title" if ns_uri else "title")
            if title_el is not None and title_el.text:
                title = title_el.text.strip()

            description = ""
            desc_el = rule_elem.find(f"{ns_uri}description" if ns_uri else "description")
            if desc_el is not None and desc_el.text:
                description = _clean_html(desc_el.text)

            fix_text = ""
            fix_el = rule_elem.find(f"{ns_uri}fixtext" if ns_uri else "fixtext")
            if fix_el is not None and fix_el.text:
                fix_text = fix_el.text.strip()

            # Extract check content (audit instructions)
            check_content = ""
            for check_el in rule_elem.iter(f"{ns_uri}check-content" if ns_uri else "check-content"):
                if check_el.text:
                    check_content = check_el.text.strip()
                    break

            # Extract references (CCI, SRG)
            refs: dict[str, list[str]] = {}
            for ident_el in rule_elem.iter(f"{ns_uri}ident" if ns_uri else "ident"):
                if ident_el.text:
                    cci = ident_el.text.strip()
                    if cci.startswith("CCI-"):
                        refs.setdefault("CCI", []).append(cci)

            if v_id:
                refs.setdefault("STIG", []).append(v_id)

            finding = ParsedFinding(
                section_number=v_id or f"STIG-{idx}",
                title=title,
                status="NOT_APPLICABLE",  # No scan results — benchmark definition only
                severity=severity,
                description=description,
                solution=fix_text,
                framework_mappings=refs,
                source_row_index=idx,
            )
            findings.append(finding)
            idx += 1

    logger.info(
        "Parsed STIG XCCDF: %d rules from '%s' v%s",
        len(findings),
        platform_info.benchmark_name,
        platform_info.benchmark_version,
    )

    return findings, platform_info


def parse_stig_ckl(content: str) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a STIG Viewer .ckl checklist file.

    Returns findings with actual compliance status from the checklist.
    """
    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(source_tool="stig_ckl", scheme="STIG")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        logger.error("Failed to parse STIG CKL XML: %s", exc)
        return findings, platform_info

    # Extract host/asset info
    asset = root.find(".//ASSET")
    if asset is not None:
        host_name = asset.findtext("HOST_NAME", "")
        host_ip = asset.findtext("HOST_IP", "")
        if host_name:
            platform_info.hostname = host_name
        if host_ip:
            platform_info.ip_address = host_ip

    # Extract STIG info
    stig_info = root.find(".//STIG_INFO")
    if stig_info is not None:
        for si_data in stig_info.findall("SI_DATA"):
            name = si_data.findtext("SID_NAME", "")
            data = si_data.findtext("SID_DATA", "")
            if name == "title" and data:
                platform_info.benchmark_name = data
                _detect_stig_platform(data, platform_info)
            elif name == "version" and data:
                platform_info.benchmark_version = data

    # Status mapping from CKL → AuditForge
    _ckl_status_map = {
        "NotAFinding": "PASS",
        "Open": "FAIL",
        "Not_Applicable": "NOT_APPLICABLE",
        "Not_Reviewed": "ERROR",
    }

    idx = 0
    for vuln in root.iter("VULN"):
        stig_data: dict[str, str] = {}
        for sd in vuln.findall("STIG_DATA"):
            attr_name = sd.findtext("VULN_ATTRIBUTE", "")
            attr_data = sd.findtext("ATTRIBUTE_DATA", "")
            if attr_name and attr_data:
                stig_data[attr_name] = attr_data

        v_id = stig_data.get("Vuln_Num", f"STIG-{idx}")
        title = stig_data.get("Rule_Title", "")
        severity_raw = stig_data.get("Severity", "medium")
        severity = _SEVERITY_MAP.get(severity_raw, "medium")

        status_raw = vuln.findtext("STATUS", "Not_Reviewed")
        status = _ckl_status_map.get(status_raw, "ERROR")

        description = stig_data.get("Vuln_Discuss", "")
        fix_text = stig_data.get("Fix_Text", "")
        check_content = stig_data.get("Check_Content", "")

        # Build references
        refs: dict[str, list[str]] = {}
        cci_ref = stig_data.get("CCI_REF", "")
        if cci_ref:
            refs["CCI"] = [c.strip() for c in cci_ref.split(",") if c.strip()]
        refs.setdefault("STIG", []).append(v_id)

        finding = ParsedFinding(
            section_number=v_id,
            title=title,
            status=status,
            severity=severity,
            description=description,
            solution=fix_text,
            actual_value=vuln.findtext("FINDING_DETAILS", ""),
            framework_mappings=refs,
            source_row_index=idx,
        )
        findings.append(finding)
        idx += 1

    logger.info(
        "Parsed STIG CKL: %d findings from '%s'",
        len(findings),
        platform_info.benchmark_name,
    )

    return findings, platform_info


# ═══════════════════════════════════════════════════════════════════════════════
#  Rule extraction
# ═══════════════════════════════════════════════════════════════════════════════

def extract_rules_from_stig(findings: list[ParsedFinding]) -> list[ExtractedRule]:
    """Convert STIG ParsedFindings into ExtractedRule objects."""
    rules: list[ExtractedRule] = []
    for f in findings:
        rule = ExtractedRule(
            section_number=f.section_number,
            title=f.title,
            description=f.description,
            severity=f.severity,
            solution=f.solution,
            framework_mappings=f.framework_mappings,
            framework="stig",
            framework_ref=f.section_number,  # V-ID
        )
        rules.append(rule)
    return rules


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_vuln_id(text: str) -> str:
    """Extract V-XXXXXX ID from STIG identifiers."""
    m = re.search(r"(V-\d+)", text)
    return m.group(1) if m else ""


def _clean_html(text: str) -> str:
    """Remove basic HTML tags from XCCDF description content."""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _detect_stig_platform(title: str, info: PlatformInfo) -> None:
    """Detect platform from a STIG benchmark title."""
    lower = title.lower()

    if "windows" in lower:
        if "server" in lower:
            info.platform = "Windows Server"
        else:
            info.platform = "Windows"
        info.platform_family = "windows"
        # Try to extract version
        m = re.search(r"(?:server\s+)?(\d{4}(?:\s*r2)?|\d{2})\b", lower)
        if m:
            info.os_version = m.group(1).strip().title()
    elif any(x in lower for x in ("red hat", "rhel")):
        info.platform = "Red Hat"
        info.platform_family = "linux"
    elif "ubuntu" in lower:
        info.platform = "Ubuntu"
        info.platform_family = "linux"
    elif "oracle linux" in lower:
        info.platform = "Oracle Linux"
        info.platform_family = "linux"
    elif "suse" in lower:
        info.platform = "SUSE"
        info.platform_family = "linux"
    elif any(x in lower for x in ("cisco", "ios", "asa")):
        info.platform = "Cisco"
        info.platform_family = "network"
    elif any(x in lower for x in ("oracle database", "oracle db")):
        info.platform = "Oracle"
        info.platform_family = "database"
    elif "apache" in lower:
        info.platform = "Apache"
        info.platform_family = "linux"
    elif "vmware" in lower:
        info.platform = "VMware"
        info.platform_family = "other"
