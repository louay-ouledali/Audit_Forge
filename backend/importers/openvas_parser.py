"""OpenVAS XML import parser — transforms OpenVAS/GVM scan exports into ParsedFindings.

OpenVAS (Greenbone Vulnerability Management) exports XML reports with structure:
  <report>
    <results>
      <result id="...">
        <host>10.0.0.1</host>
        <port>443/tcp</port>
        <nvt oid="1.3.6.1.4.1.25623.1.0.XXXXX">
          <name>Plugin Name</name>
          <family>Product Detection</family>
          <cvss_base>7.5</cvss_base>
          <severity>7.5</severity>
          <tags>cvss_base_vector=AV:N/AC:L/Au:N/C:P/I:P/A:P|summary=...|solution=...</tags>
          <refs>
            <ref type="cve" id="CVE-2024-1234"/>
            <ref type="url" id="https://..."/>
          </refs>
        </nvt>
        <threat>High</threat>
        <severity>7.5</severity>
        <description>...</description>
      </result>
    </results>
  </report>
"""

from __future__ import annotations

import logging
import re
from typing import Any
from xml.etree import ElementTree as ET

from backend.importers.base import ParsedFinding, PlatformInfo
from backend.importers.platform_detector import detect_platform_from_text

logger = logging.getLogger("auditforge.importers.openvas_parser")

_THREAT_SEVERITY = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "log": "info",
    "debug": "info",
    "alarm": "critical",
}


# ── Detection ────────────────────────────────────────────────────────

def detect_openvas_xml(content: str) -> bool:
    """Quick check whether content looks like an OpenVAS/GVM XML report."""
    if not content:
        return False
    head = content[:3000]
    # OpenVAS markers: <report>, OIDs, GVM
    if "<report " in head.lower() and ("openvas" in head.lower() or "gvm" in head.lower()):
        return True
    if "1.3.6.1.4.1.25623" in head:  # Greenbone OID prefix
        return True
    if "<results " in head.lower() and "<nvt " in content[:20000].lower():
        return True
    return False


# ── XML Parsing ──────────────────────────────────────────────────────

def parse_openvas_xml(
    content: str,
    *,
    include_vulnerabilities: bool = True,
    min_severity_score: float = 0.0,
) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse an OpenVAS/GVM XML report.

    Parameters
    ----------
    content : str
        Raw OpenVAS XML content.
    include_vulnerabilities : bool
        Include vulnerability findings.
    min_severity_score : float
        Minimum CVSS score to include (0.0 includes all).

    Returns
    -------
    tuple of (list[ParsedFinding], PlatformInfo)
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid OpenVAS XML: {exc}")

    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(source_tool="openvas")
    seen_hosts: set[str] = set()

    # Navigate to results — may be at root level or nested under <report>
    results_container = root.find(".//results")
    if results_container is None:
        results_container = root  # Fall back to searching from root

    for result in results_container.iter("result"):
        finding = _parse_result(result, platform_info, seen_hosts, min_severity_score)
        if finding:
            findings.append(finding)

    # Try to get host info from <host> elements at report level
    if not platform_info.hostname:
        for host_el in root.iter("host"):
            ip_el = host_el.find("ip") if host_el.find("ip") is not None else host_el
            if ip_el is not None and ip_el.text:
                platform_info.ip_address = ip_el.text.strip()
                platform_info.hostname = ip_el.text.strip()
                break

    # Try OS detection from host details
    for detail in root.iter("detail"):
        name_el = detail.find("name")
        value_el = detail.find("value")
        if name_el is not None and value_el is not None:
            if name_el.text == "best_os_txt" and value_el.text:
                os_info = detect_platform_from_text(value_el.text)
                platform_info.platform = os_info.platform or platform_info.platform
                platform_info.platform_family = os_info.platform_family or platform_info.platform_family
                platform_info.os_version = os_info.os_version or platform_info.os_version
                break

    logger.info(
        "OpenVAS XML: %d findings, host=%s, platform=%s",
        len(findings),
        platform_info.hostname,
        platform_info.platform,
    )

    return findings, platform_info


def _parse_result(
    result: ET.Element,
    platform_info: PlatformInfo,
    seen_hosts: set[str],
    min_severity_score: float,
) -> ParsedFinding | None:
    """Parse a single <result> element."""
    # Host and port
    host_el = result.find("host")
    port_el = result.find("port")
    host = host_el.text.strip() if host_el is not None and host_el.text else ""
    port_str = port_el.text.strip() if port_el is not None and port_el.text else ""

    # Update platform info from first host
    if host and host not in seen_hosts:
        seen_hosts.add(host)
        if not platform_info.ip_address:
            platform_info.ip_address = host
            platform_info.hostname = host

    # NVT info
    nvt = result.find("nvt")
    if nvt is None:
        return None

    oid = nvt.get("oid", "")
    name_el = nvt.find("name")
    family_el = nvt.find("family")
    nvt_name = name_el.text.strip() if name_el is not None and name_el.text else ""
    nvt_family = family_el.text.strip() if family_el is not None and family_el.text else ""

    if not nvt_name:
        return None

    # Severity
    severity_el = result.find("severity")
    threat_el = result.find("threat")

    cvss_score = 0.0
    if severity_el is not None and severity_el.text:
        try:
            cvss_score = float(severity_el.text)
        except ValueError:
            pass

    if cvss_score < min_severity_score:
        return None

    # Map CVSS to severity string
    if threat_el is not None and threat_el.text:
        severity = _THREAT_SEVERITY.get(threat_el.text.strip().lower(), "medium")
    elif cvss_score >= 9.0:
        severity = "critical"
    elif cvss_score >= 7.0:
        severity = "high"
    elif cvss_score >= 4.0:
        severity = "medium"
    elif cvss_score > 0:
        severity = "low"
    else:
        severity = "info"

    # Skip pure info/log results from detection families
    if severity == "info" and nvt_family in {"Product detection", "Service detection", "Port scanners"}:
        return None

    # Description
    desc_el = result.find("description")
    description = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

    # Parse tags for solution, summary, etc.
    tags_el = nvt.find("tags")
    tags: dict[str, str] = {}
    if tags_el is not None and tags_el.text:
        for part in tags_el.text.split("|"):
            eq_idx = part.find("=")
            if eq_idx > 0:
                tags[part[:eq_idx].strip()] = part[eq_idx + 1:].strip()

    solution = tags.get("solution", "")
    summary = tags.get("summary", "")

    # Collect references
    framework_mappings: dict[str, list[str]] = {}
    refs_el = nvt.find("refs")
    if refs_el is not None:
        cves: list[str] = []
        urls: list[str] = []
        for ref in refs_el.iter("ref"):
            ref_type = ref.get("type", "")
            ref_id = ref.get("id", "")
            if ref_type == "cve" and ref_id:
                cves.append(ref_id)
            elif ref_type == "url" and ref_id:
                urls.append(ref_id)
        if cves:
            framework_mappings["CVE"] = cves

    if cvss_score > 0:
        framework_mappings["CVSS"] = [str(cvss_score)]

    # Build title
    title = nvt_name
    if port_str and port_str != "general/tcp":
        title = f"{nvt_name} ({port_str})"

    return ParsedFinding(
        section_number=f"OVS-{oid.split('.')[-1]}" if oid else "",
        title=title,
        status="FAIL",
        severity=severity,
        actual_value=description[:2000],
        description=f"{summary}\n\n{description}" if summary else description,
        solution=solution,
        see_also="\n".join(framework_mappings.get("URL", [])) if "URL" in framework_mappings else "",
        framework_mappings=framework_mappings,
        raw_plugin_output=description,
        plugin_id=oid,
        plugin_name=nvt_name,
    )
