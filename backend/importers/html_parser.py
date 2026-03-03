"""Nessus HTML compliance report parser.

Parses Nessus HTML exports into ParsedFinding objects.
HTML structure (validated against real data):
  - Status sections: FAILED (#c2212e), PASSED (#527421), WARNING (#9f4909)
  - Per finding: title bar → Info div → Solution div → See Also div →
    References TABLE → Audit File → Policy Value → Hosts → Actual Value
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any

from backend.importers.base import ParsedFinding, PlatformInfo
from backend.importers.description_parser import parse_references, extract_profile_level

logger = logging.getLogger("auditforge.importers.html_parser")

# Status colour codes used in Nessus HTML reports
_STATUS_COLOURS: dict[str, str] = {
    "#c2212e": "FAIL",      # red   → FAILED
    "#527421": "PASS",      # green → PASSED
    "#9f4909": "NOT_APPLICABLE",  # orange → WARNING (audit not applicable)
    "c2212e": "FAIL",
    "527421": "PASS",
    "9f4909": "NOT_APPLICABLE",
}

# Known section headers in the per-finding HTML (order matters for parsing)
_SECTION_HEADERS = ("Info", "Solution", "See Also", "References", "Audit File", "Policy Value", "Hosts")


def detect_nessus_html(content: str) -> bool:
    """Return True if content looks like a Nessus HTML compliance export."""
    if not content or len(content) < 500:
        return False
    # Must be HTML
    if "<html" not in content[:2000].lower() and "<!doctype" not in content[:2000].lower():
        return False
    # Must have Nessus compliance indicators
    indicators = 0
    if "plugin-row" in content[:10000]:
        indicators += 1
    if "Compliance" in content[:200000]:
        indicators += 1
    if "toggleSection" in content[:50000]:
        indicators += 1
    if any(colour in content[:200000] for colour in ("#c2212e", "#527421", "#9f4909")):
        indicators += 1
    if "Tenable" in content or "Nessus" in content[:200000]:
        indicators += 1
    return indicators >= 2


def parse_nessus_html(content: str) -> tuple[list[ParsedFinding], PlatformInfo]:
    """Parse a Nessus HTML compliance report.

    Returns (findings, platform_info).
    """
    findings: list[ParsedFinding] = []

    # Extract title from <title> tag
    title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    report_title = title_match.group(1).strip() if title_match else ""

    # Detect platform info from title
    platform_info = PlatformInfo(source_tool="nessus")
    if report_title:
        from backend.importers.platform_detector import detect_platform_from_text
        platform_info = detect_platform_from_text(report_title)
        platform_info.source_tool = "nessus"

    # Parse findings by status sections
    # Each finding title bar has: background: #colour; ...>TITLE<
    # Pattern: div with background colour → title → container div with sections
    findings.extend(_parse_findings_from_html(content, platform_info))

    # Extract hostname from "Hosts" sections
    host_match = re.search(r'<h2>(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})</h2>', content)
    if host_match:
        platform_info.ip_address = host_match.group(1)
    else:
        host_match = re.search(r'<h2>([a-zA-Z0-9._-]+)</h2>', content)
        if host_match:
            val = host_match.group(1)
            if not val.startswith("id") and len(val) > 2:
                platform_info.hostname = val

    logger.info(
        "HTML parser: %d findings extracted (platform=%s)",
        len(findings), platform_info.platform_family or "unknown",
    )

    return findings, platform_info


def _parse_findings_from_html(content: str, platform_info: PlatformInfo) -> list[ParsedFinding]:
    """Extract individual findings from the HTML structure."""
    findings: list[ParsedFinding] = []

    # Strategy: find all title bars (div with background colour matching our status colours)
    # then parse the section-wrapper that follows each one
    title_pattern = re.compile(
        r'<div[^>]*style="[^"]*background:\s*([#0-9a-fA-F]+)[^"]*"[^>]*'
        r'(?:onclick="toggleSection\([\'"]([^"\']+)[\'"]\)")?[^>]*>'
        r'\s*(.*?)\s*<div[^>]*id="[^"]*-toggletext"',
        re.DOTALL,
    )

    for m in title_pattern.finditer(content):
        bg_colour = m.group(1).strip().lower()
        container_id = m.group(2) or ""
        raw_title = m.group(3).strip()

        # Determine status from background colour
        status = _STATUS_COLOURS.get(bg_colour)
        if not status:
            # Try without hash
            status = _STATUS_COLOURS.get(bg_colour.lstrip("#"))
        if not status:
            continue  # Not a compliance finding

        # Clean title (remove HTML tags)
        clean_title = re.sub(r"<[^>]+>", "", raw_title).strip()
        if not clean_title:
            continue

        # Extract section number from title
        sec_match = re.match(r"^(\d+(?:\.\d+)*)\s+", clean_title)
        section_number = sec_match.group(1) if sec_match else ""

        # Find the container div for this finding
        container_start = content.find(f'id="{container_id}-container"', m.end()) if container_id else -1
        if container_start < 0:
            # Fallback: find next section-wrapper after current position
            container_start = content.find('class="section-wrapper"', m.end())

        if container_start < 0:
            # Minimal finding without details
            findings.append(ParsedFinding(
                section_number=section_number,
                title=clean_title,
                status=status,
                severity="medium",
            ))
            continue

        # Find the end of this container (next title bar or end of section)
        next_title = title_pattern.search(content, container_start + 100)
        container_end = next_title.start() if next_title else len(content)
        container_html = content[container_start:container_end]

        # Parse sections within the container
        sections = _extract_sections(container_html)

        # Parse references table if present
        framework_mappings: dict[str, list[str]] = {}
        refs_html = sections.get("references", "")
        if refs_html:
            framework_mappings = _parse_references_table(refs_html)

        # Extract profile level from references
        profile_level = extract_profile_level(framework_mappings) if framework_mappings else None
        if profile_level:
            platform_info.profile_level = profile_level

        # Extract audit file
        audit_file = _clean_text(sections.get("audit_file", ""))
        if audit_file and not platform_info.benchmark_name:
            from backend.importers.platform_detector import detect_benchmark_from_name
            bm_info = detect_benchmark_from_name(audit_file)
            if bm_info.benchmark_name:
                platform_info.benchmark_name = bm_info.benchmark_name
                platform_info.benchmark_version = bm_info.benchmark_version or platform_info.benchmark_version

        # Build the description text (Info section)
        info_text = _clean_text(sections.get("info", ""))
        description, rationale, impact = _split_info_text(info_text)

        # Build finding
        finding = ParsedFinding(
            section_number=section_number,
            title=clean_title,
            status=status,
            severity="medium",  # Nessus compliance doesn't have per-rule severity
            description=description or None,
            rationale=rationale or None,
            impact=impact or None,
            solution=_clean_text(sections.get("solution", "")) or None,
            see_also=_clean_text(sections.get("see_also", "")) or None,
            policy_value=_clean_text(sections.get("policy_value", "")) or None,
            actual_value=_extract_actual_value(sections.get("hosts", "")) or None,
            framework_mappings=framework_mappings if framework_mappings else None,
        )

        findings.append(finding)

    return findings


def _extract_sections(container_html: str) -> dict[str, str]:
    """Extract named sections from a finding container div."""
    sections: dict[str, str] = {}

    # Pattern: <div class="details-header">SectionName<...>...</div> followed by content div
    header_pattern = re.compile(
        r'<div\s+class="details-header">\s*([^<]+)<',
        re.DOTALL,
    )

    headers = list(header_pattern.finditer(container_html))

    for i, hm in enumerate(headers):
        header_name = hm.group(1).strip()
        # Content starts after the header div's closing tag
        content_start = container_html.find("</div>", hm.end())
        if content_start < 0:
            continue
        content_start = content_start + len("</div>")

        # Content ends at the next header or end
        if i + 1 < len(headers):
            content_end = headers[i + 1].start()
        else:
            content_end = len(container_html)

        section_content = container_html[content_start:content_end]
        key = header_name.lower().replace(" ", "_")
        sections[key] = section_content

    return sections


def _parse_references_table(html: str) -> dict[str, list[str]]:
    """Extract framework→control mappings from the references HTML table."""
    mappings: dict[str, list[str]] = {}

    # Pattern: <td...>FRAMEWORK</td> <td...>CONTROL</td>
    row_pattern = re.compile(
        r'<td[^>]*>\s*([\w\-]+(?:\.\d+)?)\s*</td>\s*<td[^>]*>\s*(.*?)\s*</td>',
        re.DOTALL,
    )

    for rm in row_pattern.finditer(html):
        framework = rm.group(1).strip()
        control = re.sub(r"<[^>]+>", "", rm.group(2)).strip()
        if framework and control:
            mappings.setdefault(framework, []).append(control)

    return mappings


def _clean_text(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    if not html:
        return ""
    # Replace <br> with newline
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    # Remove all HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Normalize whitespace
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _split_info_text(info_text: str) -> tuple[str, str, str]:
    """Split the Info section into description, rationale, and impact."""
    description = ""
    rationale = ""
    impact = ""

    if not info_text:
        return description, rationale, impact

    # Look for Rationale: and Impact: markers
    rat_match = re.search(r"\n\s*Rationale:\s*\n", info_text)
    imp_match = re.search(r"\n\s*Impact:\s*\n", info_text)

    if rat_match and imp_match:
        description = info_text[:rat_match.start()].strip()
        rationale = info_text[rat_match.end():imp_match.start()].strip()
        impact = info_text[imp_match.end():].strip()
    elif rat_match:
        description = info_text[:rat_match.start()].strip()
        rationale = info_text[rat_match.end():].strip()
    elif imp_match:
        description = info_text[:imp_match.start()].strip()
        impact = info_text[imp_match.end():].strip()
    else:
        description = info_text

    return description, rationale, impact


def _extract_actual_value(hosts_html: str) -> str:
    """Extract the actual value from the Hosts section.

    Structure: <h2>IP</h2> ... <div style="...monospace...">ACTUAL_VALUE</div>
    """
    if not hosts_html:
        return ""

    # Look for monospace div (contains actual value)
    mono_match = re.search(
        r'<div[^>]*font-family:\s*monospace[^>]*>(.*?)</div>',
        hosts_html,
        re.DOTALL | re.IGNORECASE,
    )
    if mono_match:
        return _clean_text(mono_match.group(1))

    return ""
