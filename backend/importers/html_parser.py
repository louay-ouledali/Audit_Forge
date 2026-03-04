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
    if not content or len(content) < 200:
        return False
    # Must be HTML
    head_lower = content[:2000].lower()
    if "<html" not in head_lower and "<!doctype" not in head_lower and "<table" not in head_lower:
        return False

    # Check for compliance indicators (any 2 out of these)
    sample = content[:500000]  # Check a reasonable chunk
    indicators = 0
    if "plugin-row" in sample:
        indicators += 1
    if re.search(r'[Cc]ompliance', sample):
        indicators += 1
    if "toggleSection" in sample:
        indicators += 1
    if any(colour in sample for colour in ("#c2212e", "#527421", "#9f4909", "c2212e", "527421", "9f4909")):
        indicators += 2  # Very strong indicator
    if re.search(r'Tenable|Nessus', sample, re.IGNORECASE):
        indicators += 1
    if re.search(r'Plugin\s*ID|pluginID', sample, re.IGNORECASE):
        indicators += 1
    if re.search(r'Policy\s*Value|Actual\s*Value', sample, re.IGNORECASE):
        indicators += 1
    if re.search(r'Audit\s*File', sample, re.IGNORECASE):
        indicators += 1
    # CIS-style section numbers (e.g. 1.1.1, 2.3.4)
    if re.search(r'>\s*\d+\.\d+\.\d+\s+(?:Ensure|Configure|Set|Verify|Disable|Enable)', sample):
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
    """Extract individual findings from the HTML structure.

    Uses multiple strategies to handle different Nessus HTML export variants:
    1. Colour-coded title bars with inline style background
    2. Colour-coded title bars with background-color CSS
    3. Plugin-row class based structure
    4. Table-row based compliance results
    """
    findings: list[ParsedFinding] = []

    # ── Strategy 1: inline background: #colour ─────────────────
    # The original pattern, but much more relaxed
    strat1 = re.compile(
        r'<div[^>]*style\s*=\s*"[^"]*background(?:-color)?\s*:\s*([#0-9a-fA-F]+)[^"]*"[^>]*>(.*?)(?=<div[^>]*style\s*=\s*"[^"]*background(?:-color)?\s*:\s*[#0-9a-fA-F]+|$)',
        re.DOTALL | re.IGNORECASE,
    )
    for m in strat1.finditer(content):
        bg = m.group(1).strip().lower()
        status = _STATUS_COLOURS.get(bg) or _STATUS_COLOURS.get(bg.lstrip("#"))
        if not status:
            continue
        block = m.group(2)
        finding = _extract_finding_from_block(block, status, platform_info)
        if finding:
            findings.append(finding)

    if findings:
        logger.debug("Strategy 1 (inline bg) found %d findings", len(findings))
        return findings

    # ── Strategy 2: class-based plugin-row structure ───────────
    strat2 = re.compile(
        r'<(?:div|tr)[^>]*class\s*=\s*"[^"]*plugin-row[^"]*"[^>]*'
        r'(?:style\s*=\s*"[^"]*background(?:-color)?\s*:\s*([#0-9a-fA-F]+)[^"]*")?[^>]*>'
        r'(.*?)(?=<(?:div|tr)[^>]*class\s*=\s*"[^"]*plugin-row|$)',
        re.DOTALL | re.IGNORECASE,
    )
    for m in strat2.finditer(content):
        bg = (m.group(1) or "").strip().lower()
        status = _STATUS_COLOURS.get(bg) or _STATUS_COLOURS.get(bg.lstrip("#")) if bg else None
        block = m.group(2)
        if not status:
            status = _guess_status_from_block(block)
        if not status:
            continue
        finding = _extract_finding_from_block(block, status, platform_info)
        if finding:
            findings.append(finding)

    if findings:
        logger.debug("Strategy 2 (plugin-row) found %d findings", len(findings))
        return findings

    # ── Strategy 3: toggleSection pattern (strict) ────────────
    strat3 = re.compile(
        r'<div[^>]*(?:onclick\s*=\s*"toggleSection\([\'"]([^"\']+)[\'"]\)")?[^>]*style\s*=\s*"[^"]*background(?:-color)?\s*:\s*([#0-9a-fA-F]+)[^"]*"[^>]*>'
        r'\s*(.*?)\s*</div>',
        re.DOTALL | re.IGNORECASE,
    )
    for m in strat3.finditer(content):
        container_id = m.group(1) or ""
        bg = m.group(2).strip().lower()
        raw_title = m.group(3).strip()

        status = _STATUS_COLOURS.get(bg) or _STATUS_COLOURS.get(bg.lstrip("#"))
        if not status:
            continue

        clean_title = re.sub(r"<[^>]+>", "", raw_title).strip()
        if not clean_title:
            continue

        sec_match = re.match(r"^(\d+(?:\.\d+)*)\s+", clean_title)
        section_number = sec_match.group(1) if sec_match else ""

        # Try to find the container
        sections: dict[str, str] = {}
        if container_id:
            container_start = content.find(f'id="{container_id}', m.end())
            if container_start >= 0:
                next_match = strat3.search(content, container_start + 100)
                container_end = next_match.start() if next_match else min(container_start + 20000, len(content))
                sections = _extract_sections(content[container_start:container_end])

        findings.append(ParsedFinding(
            section_number=section_number,
            title=clean_title,
            status=status,
            severity="medium",
            description=_clean_text(sections.get("info", "")) or None,
            solution=_clean_text(sections.get("solution", "")) or None,
            see_also=_clean_text(sections.get("see_also", "")) or None,
            policy_value=_clean_text(sections.get("policy_value", "")) or None,
            actual_value=_extract_actual_value(sections.get("hosts", "")) or None,
        ))

    if findings:
        logger.debug("Strategy 3 (toggleSection) found %d findings", len(findings))
        return findings

    # ── Strategy 4: generic colour-code sweep ─────────────────
    # Find ALL colour occurrences and extract surrounding text as findings
    colour_pattern = re.compile(
        r'(?:background(?:-color)?|color)\s*:\s*(#?(?:c2212e|527421|9f4909))',
        re.IGNORECASE,
    )
    # Collect positions of compliance-coloured elements
    positions: list[tuple[int, str]] = []
    for m in colour_pattern.finditer(content):
        colour = m.group(1).strip().lower()
        status = _STATUS_COLOURS.get(colour) or _STATUS_COLOURS.get(colour.lstrip("#"))
        if status:
            positions.append((m.start(), status))

    for idx, (pos, status) in enumerate(positions):
        # Extract context: go back to find the enclosing div start
        block_start = max(0, content.rfind("<div", max(0, pos - 500), pos))
        block_end = positions[idx + 1][0] if idx + 1 < len(positions) else min(pos + 10000, len(content))
        block = content[block_start:block_end]

        finding = _extract_finding_from_block(block, status, platform_info)
        if finding:
            findings.append(finding)

    if findings:
        logger.debug("Strategy 4 (colour sweep) found %d findings", len(findings))

    return findings


def _extract_finding_from_block(block: str, status: str, platform_info: PlatformInfo) -> ParsedFinding | None:
    """Extract a ParsedFinding from an HTML block that contains one compliance result."""
    # Extract title: look for text that starts with a section number (e.g. "1.1.1 ...")
    title_patterns = [
        # Section number at start of visible text
        re.compile(r'>\s*(\d+(?:\.\d+)+\s+[^<]{5,}?)\s*<', re.DOTALL),
        # Bold section number
        re.compile(r'<(?:b|strong|h[1-6])[^>]*>\s*(\d+(?:\.\d+)+\s+[^<]{5,}?)\s*</(?:b|strong|h[1-6])>', re.DOTALL | re.IGNORECASE),
        # Any text with "Ensure" or "Configure" (common CIS rule titles)
        re.compile(r'>\s*((?:Ensure|Configure|Set|Verify|Disable|Enable|Restrict|Audit)\s+[^<]{5,}?)\s*<', re.DOTALL | re.IGNORECASE),
    ]

    title = ""
    section_number = ""

    for tp in title_patterns:
        tm = tp.search(block)
        if tm:
            candidate = re.sub(r'\s+', ' ', tm.group(1)).strip()
            # Skip very short or very long
            if 10 < len(candidate) < 500:
                title = candidate
                sec_match = re.match(r'^(\d+(?:\.\d+)+)\s+', title)
                section_number = sec_match.group(1) if sec_match else ""
                break

    if not title:
        return None

    # Extract sections  
    sections = _extract_sections(block)

    # Also try direct extraction patterns for common fields
    desc = _clean_text(sections.get("info", ""))
    solution = _clean_text(sections.get("solution", ""))
    policy_value = _clean_text(sections.get("policy_value", ""))
    actual_value = _extract_actual_value(sections.get("hosts", ""))

    # Try alternative extraction if sections didn't yield results
    if not policy_value:
        pv_match = re.search(r'Policy\s*Value\s*:?\s*</(?:b|strong|div|td|th)[^>]*>\s*(?:<[^>]+>)?\s*([^<]+)', block, re.IGNORECASE)
        if pv_match:
            policy_value = pv_match.group(1).strip()

    if not actual_value:
        av_match = re.search(r'Actual\s*Value\s*:?\s*</(?:b|strong|div|td|th)[^>]*>\s*(?:<[^>]+>)?\s*([^<]+)', block, re.IGNORECASE)
        if av_match:
            actual_value = av_match.group(1).strip()

    # Extract references
    framework_mappings = _parse_references_table(block)
    if framework_mappings:
        profile_level = extract_profile_level(framework_mappings)
        if profile_level:
            platform_info.profile_level = profile_level

    # Extract audit file info for platform detection
    audit_match = re.search(r'[Aa]udit\s*[Ff]ile\s*:?\s*</(?:b|strong|div|td|th)[^>]*>\s*(?:<[^>]+>)?\s*([^<]+)', block)
    if audit_match and not platform_info.benchmark_name:
        from backend.importers.platform_detector import detect_benchmark_from_name
        bm_info = detect_benchmark_from_name(audit_match.group(1).strip())
        if bm_info.benchmark_name:
            platform_info.benchmark_name = bm_info.benchmark_name
            platform_info.benchmark_version = bm_info.benchmark_version or platform_info.benchmark_version

    return ParsedFinding(
        section_number=section_number,
        title=title,
        status=status,
        severity="medium",
        description=desc or None,
        solution=solution or None,
        policy_value=policy_value or None,
        actual_value=actual_value or None,
        framework_mappings=framework_mappings if framework_mappings else None,
    )


def _guess_status_from_block(block: str) -> str | None:
    """Try to guess PASS/FAIL status from block text when no colour is available."""
    block_lower = block.lower()
    for colour_code, status in _STATUS_COLOURS.items():
        if colour_code in block_lower:
            return status
    # Check for explicit status text
    if re.search(r'\bFAILED?\b', block):
        return "FAIL"
    if re.search(r'\bPASSED?\b', block):
        return "PASS"
    if re.search(r'\bWARNING\b', block):
        return "NOT_APPLICABLE"
    return None


def _extract_sections(container_html: str) -> dict[str, str]:
    """Extract named sections from a finding container div.

    Supports multiple HTML structures:
    1. <div class="details-header">SectionName</div> ... content ...
    2. <b>SectionName:</b> ... content ...
    3. <th>SectionName</th><td>content</td>
    4. <div class="...header...">SectionName</div>
    """
    sections: dict[str, str] = {}

    # Known section names to look for
    known_headers = {
        "info": "info", "information": "info",
        "description": "info",
        "solution": "solution", "remediation": "solution",
        "see also": "see_also", "see_also": "see_also",
        "references": "references", "reference": "references",
        "audit file": "audit_file", "audit_file": "audit_file",
        "policy value": "policy_value", "policy_value": "policy_value",
        "expected value": "policy_value",
        "hosts": "hosts",
        "actual value": "actual_value", "actual_value": "actual_value",
        "output": "actual_value",
        "rationale": "rationale",
        "impact": "impact",
    }

    # Strategy 1: <div class="details-header">Header<
    header_pattern = re.compile(
        r'<div\s+class="[^"]*(?:details-header|section-header|header)[^"]*"[^>]*>\s*([^<]+)<',
        re.DOTALL | re.IGNORECASE,
    )
    headers = list(header_pattern.finditer(container_html))
    if headers:
        for i, hm in enumerate(headers):
            header_name = hm.group(1).strip()
            key = known_headers.get(header_name.lower().replace(" ", "_"), header_name.lower().replace(" ", "_"))
            content_start = container_html.find("</div>", hm.end())
            if content_start < 0:
                continue
            content_start += len("</div>")
            content_end = headers[i + 1].start() if i + 1 < len(headers) else len(container_html)
            sections[key] = container_html[content_start:content_end]
        return sections

    # Strategy 2: <b>Header:</b> or <strong>Header:</strong>
    bold_pattern = re.compile(
        r'<(?:b|strong)[^>]*>\s*(Info|Solution|See Also|References?|Audit File|Policy Value|Hosts?|Actual Value|Description|Rationale|Impact)\s*:?\s*</(?:b|strong)>',
        re.IGNORECASE,
    )
    bold_headers = list(bold_pattern.finditer(container_html))
    if bold_headers:
        for i, bm in enumerate(bold_headers):
            header_name = bm.group(1).strip()
            key = known_headers.get(header_name.lower(), header_name.lower().replace(" ", "_"))
            content_start = bm.end()
            content_end = bold_headers[i + 1].start() if i + 1 < len(bold_headers) else len(container_html)
            sections[key] = container_html[content_start:content_end]
        return sections

    # Strategy 3: table header/data pairs
    table_pattern = re.compile(
        r'<t[hd][^>]*>\s*(Info|Solution|See Also|References?|Audit File|Policy Value|Hosts?|Actual Value)\s*:?\s*</t[hd]>\s*<td[^>]*>(.*?)</td>',
        re.DOTALL | re.IGNORECASE,
    )
    for tm in table_pattern.finditer(container_html):
        header_name = tm.group(1).strip()
        key = known_headers.get(header_name.lower(), header_name.lower().replace(" ", "_"))
        sections[key] = tm.group(2)

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
