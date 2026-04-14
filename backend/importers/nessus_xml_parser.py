""".nessus XML parser — transforms Nessus .nessus exports into ParsedFindings.

The .nessus format is Nessus's native XML export containing full scan data.
It supports both compliance checks and vulnerability findings.

XML structure (simplified):
  <NessusClientData_v2>
    <Policy>...</Policy>
    <Report name="...">
      <ReportHost name="ip_or_hostname">
        <HostProperties>
          <tag name="host-ip">10.0.0.1</tag>
          <tag name="host-fqdn">server.local</tag>
          <tag name="operating-system">Microsoft Windows 11</tag>
          ...
        </HostProperties>
        <ReportItem port="0" svc_name="" protocol="" severity="0"
                    pluginID="21156" pluginName="..." pluginFamily="...">
          <compliance-check-id>...</compliance-check-id>
          <compliance-result>PASSED</compliance-result>
          <compliance-actual-value>...</compliance-actual-value>
          <compliance-policy-value>...</compliance-policy-value>
          <compliance-info>...</compliance-info>
          <compliance-solution>...</compliance-solution>
          <compliance-reference>...</compliance-reference>
          <description>...</description>
          <plugin_output>...</plugin_output>
          <risk_factor>NONE</risk_factor>
          <solution>...</solution>
          <see_also>...</see_also>
          <synopsis>...</synopsis>
        </ReportItem>
        ...
      </ReportHost>
    </Report>
  </NessusClientData_v2>

Compliance items use pluginID 21156/21157/33929/33930 and have
compliance-* child elements.

Vulnerability items have risk_factor, severity attribute, CVE references, etc.
"""

from __future__ import annotations

import logging
import re
from typing import Any
import defusedxml.ElementTree as ET

from backend.importers.base import ExtractedRule, ParsedFinding, PlatformInfo
from backend.importers.description_parser import parse_references
from backend.importers.platform_detector import detect_platform_from_text

logger = logging.getLogger("auditforge.importers.nessus_xml_parser")

# Plugin IDs that indicate compliance check results
COMPLIANCE_PLUGIN_IDS = {"21156", "21157", "33929", "33930"}

_SEVERITY_MAP = {
    "0": "info",
    "1": "low",
    "2": "medium",
    "3": "high",
    "4": "critical",
}

_STATUS_MAP = {
    "PASSED": "PASS",
    "PASS": "PASS",
    "FAILED": "FAIL",
    "FAIL": "FAIL",
    "WARNING": "NOT_APPLICABLE",
    "ERROR": "ERROR",
}

_RISK_SEVERITY = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "none": "info",
}


def detect_nessus_xml(content: str) -> bool:
    """Quick check whether content looks like a .nessus XML file."""
    if not content:
        return False
    head = content[:2000]
    return "NessusClientData_v2" in head or ("<Report " in head and "<ReportHost " in content[:10000])


def parse_nessus_xml(
    content: str,
    *,
    include_compliance: bool = True,
    include_vulnerabilities: bool = True,
) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a .nessus XML export.

    Parameters
    ----------
    content : str
        Raw .nessus XML content.
    include_compliance : bool
        Include compliance check findings.
    include_vulnerabilities : bool
        Include vulnerability findings (Phase 4 feature).

    Returns
    -------
    tuple of (list[ParsedFinding], PlatformInfo)
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}")

    findings: list[ParsedFinding] = []
    platform_info = PlatformInfo(source_tool="nessus")

    # Find all ReportHost elements
    for report in root.iter("Report"):
        for host in report.iter("ReportHost"):
            host_name = host.get("name", "")
            host_props = _parse_host_properties(host)

            # Update platform info from first host
            if not platform_info.hostname:
                platform_info.hostname = host_props.get("host-fqdn") or host_name
                platform_info.ip_address = host_props.get("host-ip") or host_name
                os_str = host_props.get("operating-system", "")
                if os_str:
                    os_info = detect_platform_from_text(os_str)
                    platform_info.platform = os_info.platform or platform_info.platform
                    platform_info.platform_family = os_info.platform_family or platform_info.platform_family
                    platform_info.os_version = os_info.os_version or platform_info.os_version

            # Parse each ReportItem
            for item in host.iter("ReportItem"):
                plugin_id = item.get("pluginID", "")
                severity_attr = item.get("severity", "0")
                is_compliance = plugin_id in COMPLIANCE_PLUGIN_IDS

                # Extract port scan data from Plugin 34220
                if plugin_id == "34220":
                    _extract_port_from_xml_item(item, platform_info)
                    continue

                # Also collect open ports from ANY ReportItem with port > 0
                _item_port = item.get("port", "0")
                if _item_port and _item_port != "0":
                    _extract_port_from_xml_item(item, platform_info)

                if is_compliance and include_compliance:
                    finding = _parse_compliance_item(item, plugin_id, host_props)
                    if finding:
                        findings.append(finding)
                elif not is_compliance and include_vulnerabilities:
                    finding = _parse_vulnerability_item(item, plugin_id, severity_attr, host_props)
                    if finding:
                        findings.append(finding)

    # Try to detect benchmark from compliance item names
    if findings:
        _detect_benchmark_info(findings, platform_info)

    logger.info(
        "Parsed .nessus XML: %d findings (%d compliance, %d vuln), host=%s, platform=%s",
        len(findings),
        sum(1 for f in findings if f.plugin_id in COMPLIANCE_PLUGIN_IDS),
        sum(1 for f in findings if f.plugin_id not in COMPLIANCE_PLUGIN_IDS),
        platform_info.hostname,
        platform_info.platform,
    )

    return findings, platform_info


def _parse_host_properties(host_elem: ET.Element) -> dict[str, str]:
    """Extract host properties from <HostProperties> element."""
    props: dict[str, str] = {}
    hp = host_elem.find("HostProperties")
    if hp is not None:
        for tag in hp.iter("tag"):
            name = tag.get("name", "")
            value = tag.text or ""
            if name:
                props[name] = value
    return props


def _extract_port_from_xml_item(item: ET.Element, info: PlatformInfo) -> None:
    """Extract an open port from a ReportItem element.

    Captures the Nessus ``svc_name`` attribute so the report can display
    a meaningful service name instead of just "tcp" / "udp".
    """
    port_str = item.get("port", "0")
    protocol = item.get("protocol", "tcp").lower()
    try:
        port_num = int(port_str)
    except (ValueError, TypeError):
        return
    if port_num <= 0:
        return
    svc_name = (item.get("svc_name", "") or "").strip()
    # Skip uninformative generic labels
    if svc_name in ("", "?", "general"):
        svc_name = ""
    for existing in info.open_ports:
        if existing.get("port") == port_num and existing.get("protocol") == protocol:
            # Upgrade service name if we now have one and the existing entry doesn't
            if svc_name and not existing.get("service"):
                existing["service"] = svc_name.upper()
            return
    entry: dict[str, object] = {"port": port_num, "protocol": protocol}
    if svc_name:
        entry["service"] = svc_name.upper()
    info.open_ports.append(entry)


_CM_NS = "{http://www.nessus.org/cm}"


def _get_text(elem: ET.Element, tag: str) -> str:
    """Get text content of a child element, or empty string.

    Handles the ``cm:`` namespace prefix used by real Nessus exports
    (``xmlns:cm="http://www.nessus.org/cm"``).  Tries plain tag first,
    then namespaced.
    """
    child = elem.find(tag)
    if child is None:
        child = elem.find(f"{_CM_NS}{tag}")
    return (child.text or "").strip() if child is not None else ""


def _parse_compliance_item(
    item: ET.Element,
    plugin_id: str,
    host_props: dict[str, str],
) -> ParsedFinding | None:
    """Parse a compliance check ReportItem."""
    result = _get_text(item, "compliance-result")
    if not result:
        return None

    status = _STATUS_MAP.get(result.upper(), "MANUAL_REVIEW")

    # Extract compliance-specific fields
    check_name = _get_text(item, "compliance-check-name") or item.get("pluginName", "")
    info = _get_text(item, "compliance-info")
    solution = _get_text(item, "compliance-solution")
    actual = _get_text(item, "compliance-actual-value")
    policy = _get_text(item, "compliance-policy-value")
    reference_raw = _get_text(item, "compliance-reference")
    see_also = _get_text(item, "compliance-see-also") or _get_text(item, "see_also")

    # Parse section number from check name (e.g., "1.2.3 Ensure ...")
    section_number = ""
    title = check_name
    m = re.match(r"^(\d+(?:\.\d+)+)\s+(.+)", check_name)
    if m:
        section_number = m.group(1)
        title = m.group(2)

    # Skip .audit file reference metadata entries
    if re.search(r"\.audit\s+from\s+", check_name, re.IGNORECASE):
        return None

    # Parse framework references
    framework_mappings: dict[str, list[str]] = {}
    if reference_raw:
        framework_mappings = parse_references(reference_raw)

    return ParsedFinding(
        section_number=section_number,
        title=title,
        status=status,
        severity="medium",  # Compliance checks are medium by default
        actual_value=actual,
        policy_value=policy,
        description=info,
        solution=solution,
        see_also=see_also,
        framework_mappings=framework_mappings,
        raw_plugin_output=_get_text(item, "plugin_output"),
        plugin_id=plugin_id,
        plugin_name=item.get("pluginName", ""),
    )


def _parse_vulnerability_item(
    item: ET.Element,
    plugin_id: str,
    severity_attr: str,
    host_props: dict[str, str],
) -> ParsedFinding | None:
    """Parse a vulnerability ReportItem."""
    plugin_name = item.get("pluginName", "")
    if not plugin_name:
        return None

    # Skip informational scan infrastructure plugins
    if plugin_id in {"19506", "34220", "141118", "10180", "11219", "25220"}:
        return None

    risk_factor = _get_text(item, "risk_factor").lower()
    severity = _RISK_SEVERITY.get(risk_factor) or _SEVERITY_MAP.get(severity_attr, "info")

    # Skip info-level unless they have useful data
    if severity == "info" and not _get_text(item, "exploit_available"):
        return None

    description = _get_text(item, "description")
    synopsis = _get_text(item, "synopsis")
    solution = _get_text(item, "solution")
    see_also = _get_text(item, "see_also")
    plugin_output = _get_text(item, "plugin_output")

    # Collect CVEs
    cves = [el.text for el in item.iter("cve") if el.text]
    # Collect BIDs
    bids = [el.text for el in item.iter("bid") if el.text]
    # Collect CVSS
    cvss_base = _get_text(item, "cvss_base_score")
    cvss3_base = _get_text(item, "cvss3_base_score")

    framework_mappings: dict[str, list[str]] = {}
    if cves:
        framework_mappings["CVE"] = cves
    if bids:
        framework_mappings["BID"] = bids
    if cvss3_base:
        framework_mappings["CVSS3"] = [cvss3_base]
    elif cvss_base:
        framework_mappings["CVSS"] = [cvss_base]

    # Determine status: vuln items are always FAIL (they exist because they're found)
    port = item.get("port", "0")
    protocol = item.get("protocol", "")
    svc_name = item.get("svc_name", "")

    title_parts = [plugin_name]
    if port != "0" and svc_name:
        title_parts.append(f"({svc_name}/{port}/{protocol})")

    return ParsedFinding(
        section_number=f"VLN-{plugin_id}",
        title=" ".join(title_parts),
        status="FAIL",  # Vulnerability found = finding
        severity=severity,
        actual_value=plugin_output[:2000] if plugin_output else "",
        description=f"{synopsis}\n\n{description}" if synopsis else description,
        solution=solution,
        see_also=see_also,
        framework_mappings=framework_mappings,
        raw_plugin_output=plugin_output,
        plugin_id=plugin_id,
        plugin_name=plugin_name,
    )


def _detect_benchmark_info(findings: list[ParsedFinding], info: PlatformInfo) -> None:
    """Try to detect benchmark name from the compliance findings."""
    for f in findings:
        if f.plugin_id in COMPLIANCE_PLUGIN_IDS and f.plugin_name:
            name = f.plugin_name
            # Nessus plugin names often contain the benchmark reference
            # e.g. "CIS Microsoft Windows 11 Enterprise Benchmark v5.0.0 - ..."
            m = re.search(r"(CIS\s+.+?Benchmark)\s*v?(\d+\.\d+\.\d+)?", name, re.IGNORECASE)
            if m:
                info.benchmark_name = m.group(1).strip()
                if m.group(2):
                    info.benchmark_version = m.group(2)
                info.scheme = "CIS"
                return
    # Fallback: use platform + family
    if info.platform and not info.benchmark_name:
        info.benchmark_name = f"CIS {info.platform} Benchmark"


def extract_rules_from_findings(findings: list[ParsedFinding]) -> list[ExtractedRule]:
    """Extract unique rule specifications from parsed findings (compliance only)."""
    seen: set[str] = set()
    rules: list[ExtractedRule] = []

    for f in findings:
        if f.plugin_id not in COMPLIANCE_PLUGIN_IDS:
            continue
        key = f.section_number or f.title
        if key in seen:
            continue
        seen.add(key)

        rules.append(ExtractedRule(
            section_number=f.section_number,
            title=f.title,
            description=f.description,
            solution=f.solution,
            see_also=f.see_also,
            severity=f.severity,
            framework_mappings=f.framework_mappings,
            expected_value=f.policy_value,
        ))

    return rules
