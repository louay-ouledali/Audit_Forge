"""Qualys CSV/XML import parser — transforms Qualys scan exports into ParsedFindings.

Supports:
- Qualys VM CSV export (Vulnerability Management scan results)
- Qualys Policy Compliance CSV export
- Qualys XML exports (basic support)

Qualys VM CSV columns typically include:
  IP, DNS, NetBIOS, OS, QID, Title, Vuln Status, Severity, Port, Protocol,
  FQDN, SSL, CVE ID, Vendor Reference, Bugtraq ID, CVSS Base, CVSS3 Base,
  Threat, Impact, Solution, Exploitability, Results

Qualys Policy Compliance CSV columns typically include:
  IP, DNS, Control ID, Technology, Control Statement, Status, Criticality,
  Extended Evidence, Exception, Remediation, Reference
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any
import defusedxml.ElementTree as ET

from backend.importers.base import ExtractedRule, ParsedFinding, PlatformInfo
from backend.importers.platform_detector import detect_platform_from_text

logger = logging.getLogger("auditforge.importers.qualys_parser")

_SEVERITY_MAP = {
    "1": "info",
    "2": "low",
    "3": "medium",
    "4": "high",
    "5": "critical",
}

# Qualys Policy Compliance status mapping
_COMPLIANCE_STATUS = {
    "Passed": "PASS",
    "PASS": "PASS",
    "Failed": "FAIL",
    "FAIL": "FAIL",
    "Error": "ERROR",
    "Not Applicable": "NOT_APPLICABLE",
}


# ── Detection ────────────────────────────────────────────────────────

def detect_qualys_csv(content: str) -> bool:
    """Quick check whether CSV content looks like a Qualys export."""
    if not content:
        return False
    head = content[:3000].lower()
    # VM scan export markers
    if "qid" in head and ("vuln status" in head or "vulnerability" in head):
        return True
    # Policy compliance markers
    if "control id" in head and "control statement" in head:
        return True
    return False


def detect_qualys_xml(content: str) -> bool:
    """Quick check whether XML content looks like a Qualys export."""
    if not content:
        return False
    head = content[:2000]
    return "QUALYS" in head.upper() or "<SCAN " in head or "<COMPLIANCE_" in head.upper()


# ── CSV Parsing ──────────────────────────────────────────────────────

def parse_qualys_csv(
    content: str,
    *,
    include_compliance: bool = True,
    include_vulnerabilities: bool = True,
) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a Qualys CSV export (VM scan or Policy Compliance).

    Returns (findings, platform_info).
    """
    reader = csv.DictReader(io.StringIO(content))
    fieldnames = set(f.lower() for f in (reader.fieldnames or []))

    # Determine format variant
    is_compliance = "control id" in fieldnames and "control statement" in fieldnames
    is_vm = "qid" in fieldnames

    if is_compliance and include_compliance:
        return _parse_compliance_csv(reader, fieldnames)
    elif is_vm and include_vulnerabilities:
        return _parse_vm_csv(reader, fieldnames)
    else:
        logger.warning("Qualys CSV format not recognized or excluded by filter")
        return [], PlatformInfo(source_tool="qualys")


def _parse_compliance_csv(
    reader: csv.DictReader,
    fieldnames: set[str],
) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse Qualys Policy Compliance CSV."""
    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(source_tool="qualys")
    seen_os: set[str] = set()

    for idx, row in enumerate(reader):
        row_lower = {k.lower(): v for k, v in row.items()}

        control_id = row_lower.get("control id", "").strip()
        statement = row_lower.get("control statement", "").strip()
        status_raw = row_lower.get("status", "").strip()
        criticality = row_lower.get("criticality", "").strip()
        evidence = row_lower.get("extended evidence", "").strip()
        remediation = row_lower.get("remediation", "").strip()
        reference = row_lower.get("reference", "").strip()
        technology = row_lower.get("technology", "").strip()
        ip = row_lower.get("ip", "").strip()
        dns = row_lower.get("dns", "").strip()

        status = _COMPLIANCE_STATUS.get(status_raw, "MANUAL_REVIEW")
        severity = _SEVERITY_MAP.get(criticality, "medium")

        # Platform detection from technology / OS columns
        os_str = row_lower.get("os", "") or technology
        if os_str and os_str not in seen_os:
            seen_os.add(os_str)
            if not platform_info.platform:
                os_info = detect_platform_from_text(os_str)
                platform_info.platform = os_info.platform
                platform_info.platform_family = os_info.platform_family
                platform_info.os_version = os_info.os_version

        if not platform_info.hostname and dns:
            platform_info.hostname = dns
        if not platform_info.ip_address and ip:
            platform_info.ip_address = ip

        finding = ParsedFinding(
            section_number=control_id,
            title=statement,
            status=status,
            severity=severity,
            actual_value=evidence[:2000] if evidence else "",
            description=statement,
            solution=remediation,
            see_also=reference,
            plugin_id=f"QPC-{control_id}",
            plugin_name=f"Qualys Compliance: {statement[:80]}",
            source_row_index=idx,
        )
        findings.append(finding)

    logger.info("Qualys compliance CSV: %d findings", len(findings))
    return findings, platform_info


def _parse_vm_csv(
    reader: csv.DictReader,
    fieldnames: set[str],
) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse Qualys VM (Vulnerability Management) CSV."""
    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(source_tool="qualys")

    for idx, row in enumerate(reader):
        row_lower = {k.lower(): v for k, v in row.items()}

        qid = row_lower.get("qid", "").strip()
        title = row_lower.get("title", "").strip()
        severity = row_lower.get("severity", "").strip()
        ip = row_lower.get("ip", "").strip()
        dns = row_lower.get("dns", "").strip()
        os_str = row_lower.get("os", "").strip()
        port = row_lower.get("port", "").strip()
        protocol = row_lower.get("protocol", "").strip()
        cve_ids = row_lower.get("cve id", "").strip()
        cvss_base = row_lower.get("cvss base", "").strip()
        cvss3_base = row_lower.get("cvss3 base", "").strip()
        threat = row_lower.get("threat", "").strip()
        impact = row_lower.get("impact", "").strip()
        solution = row_lower.get("solution", "").strip()
        results = row_lower.get("results", "").strip()

        if not qid and not title:
            continue

        # Update platform info
        if not platform_info.hostname and dns:
            platform_info.hostname = dns
        if not platform_info.ip_address and ip:
            platform_info.ip_address = ip
        if not platform_info.platform and os_str:
            os_info = detect_platform_from_text(os_str)
            platform_info.platform = os_info.platform
            platform_info.platform_family = os_info.platform_family
            platform_info.os_version = os_info.os_version

        sev = _SEVERITY_MAP.get(severity, "medium")

        # Framework mappings
        framework_mappings: dict[str, list[str]] = {}
        if cve_ids:
            cves = [c.strip() for c in cve_ids.split(",") if c.strip()]
            if cves:
                framework_mappings["CVE"] = cves
        if cvss3_base:
            framework_mappings["CVSS3"] = [cvss3_base]
        elif cvss_base:
            framework_mappings["CVSS"] = [cvss_base]

        title_full = title
        if port and port != "0":
            title_full = f"{title} ({protocol}/{port})"

        finding = ParsedFinding(
            section_number=f"QID-{qid}",
            title=title_full,
            status="FAIL",  # Qualys VM only reports found vulnerabilities
            severity=sev,
            actual_value=results[:2000] if results else "",
            description=f"{threat}\n\n{impact}" if threat else impact,
            solution=solution,
            framework_mappings=framework_mappings,
            raw_plugin_output=results,
            plugin_id=f"QID-{qid}",
            plugin_name=title,
            source_row_index=idx,
        )
        findings.append(finding)

    logger.info("Qualys VM CSV: %d findings", len(findings))
    return findings, platform_info


# ── XML Parsing (basic support) ─────────────────────────────────────

def parse_qualys_xml(
    content: str,
    *,
    include_compliance: bool = True,
    include_vulnerabilities: bool = True,
) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a Qualys XML export. Basic implementation."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid Qualys XML: {exc}")

    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(source_tool="qualys")

    # Try to find vulnerability results
    for vuln in root.iter("VULN"):
        qid_el = vuln.find(".//QID")
        title_el = vuln.find(".//TITLE")
        severity_el = vuln.find(".//SEVERITY")
        result_el = vuln.find(".//RESULT")
        solution_el = vuln.find(".//SOLUTION")
        impact_el = vuln.find(".//IMPACT")

        qid = qid_el.text if qid_el is not None else ""
        title = title_el.text if title_el is not None else ""
        severity = _SEVERITY_MAP.get(
            severity_el.text if severity_el is not None else "3", "medium"
        )

        if not qid and not title:
            continue

        finding = ParsedFinding(
            section_number=f"QID-{qid}",
            title=title,
            status="FAIL",
            severity=severity,
            actual_value=(result_el.text or "")[:2000] if result_el is not None else "",
            description=(impact_el.text or "") if impact_el is not None else "",
            solution=(solution_el.text or "") if solution_el is not None else "",
            plugin_id=f"QID-{qid}",
            plugin_name=title,
        )
        findings.append(finding)

    logger.info("Qualys XML: %d findings", len(findings))
    return findings, platform_info
