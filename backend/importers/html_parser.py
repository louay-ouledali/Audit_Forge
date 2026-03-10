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

    Uses position-based scanning (O(n)) rather than full-file regexes to
    handle multi-MB Nessus reports efficiently.

    Strategy:
      1. Find every ``<div>`` whose ``style`` contains one of the three
         compliance background colours (#c2212e, #527421, #9f4909).
      2. Slice the content between consecutive colour-bars to get each
         finding's HTML block (title bar + details container).
      3. Parse the title and detail sections from each block.
    """
    findings: list[ParsedFinding] = []

    # ── Step 1: locate all compliance-coloured title bars ──────
    # These divs use inline ``background: #COLOUR`` (no "background-color")
    bar_re = re.compile(
        r'<div\b[^>]*?\bstyle\s*=\s*"[^"]*?\bbackground(?:-color)?\s*:\s*'
        r'(#?(?:c2212e|527421|9f4909))\b[^"]*"[^>]*>',
        re.IGNORECASE,
    )

    bars: list[tuple[int, int, str]] = []  # (div_start, after_tag, status)
    for m in bar_re.finditer(content):
        colour = m.group(1).strip().lower()
        status = _STATUS_COLOURS.get(colour) or _STATUS_COLOURS.get(colour.lstrip("#"))
        if status:
            bars.append((m.start(), m.end(), status))

    logger.info("HTML parser: found %d compliance-coloured title bars", len(bars))

    if not bars:
        return findings

    # ── Step 2: for each bar, extract the finding block ────────
    for i, (bar_start, tag_end, status) in enumerate(bars):
        # Block: from tag_end to the START of the next colour-bar
        next_start = bars[i + 1][0] if i + 1 < len(bars) else min(bar_start + 50_000, len(content))
        block = content[tag_end:next_start]

        # ── Title extraction ──────────────────────────────────
        # The title is the direct text child of the title-bar div, before the
        # nested <div id="…-toggletext"> child.
        title_end_idx = block.find("<div")
        if title_end_idx < 0:
            title_end_idx = block.find("</div")
        raw_title = block[:title_end_idx] if title_end_idx > 0 else ""
        raw_title = re.sub(r"<[^>]+>", "", raw_title)
        raw_title = re.sub(r"\s+", " ", raw_title).strip()

        if not raw_title or len(raw_title) < 3:
            # Fallback: search for a section-numbered line anywhere in block
            tm = re.search(r">\s*(\d+(?:\.\d+)+\s+[^<]{5,}?)\s*<", block)
            if tm:
                raw_title = re.sub(r"\s+", " ", tm.group(1)).strip()
            else:
                # Last resort: any text with CIS keywords
                tm = re.search(
                    r">\s*((?:Ensure|Configure|Set|Verify|Disable|Enable|Restrict|Audit)\s+[^<]{5,}?)\s*<",
                    block, re.IGNORECASE,
                )
                if tm:
                    raw_title = re.sub(r"\s+", " ", tm.group(1)).strip()
                else:
                    continue

        sec_match = re.match(r"^(\d+(?:\.\d+)+)\s+", raw_title)
        section_number = sec_match.group(1) if sec_match else ""

        # Skip .audit file reference metadata entries (not real compliance checks)
        if re.search(r"\.audit\s+from\s+", raw_title, re.IGNORECASE):
            continue

        # ── Detail section extraction ─────────────────────────
        sections = _extract_sections(block)

        # ── Framework references ──────────────────────────────
        framework_mappings = _parse_references_table(block)
        if framework_mappings:
            profile_level = extract_profile_level(framework_mappings)
            if profile_level and not platform_info.profile_level:
                platform_info.profile_level = profile_level

        # ── Platform detection from audit file ────────────────
        audit_file = _clean_text(sections.get("audit_file", ""))
        if audit_file and not platform_info.platform:
            from backend.importers.platform_detector import detect_benchmark_from_name
            # Normalize audit filename: strip extension, underscores→spaces,
            # expand common abbreviations
            normalised = re.sub(r'\.audit$', '', audit_file, flags=re.IGNORECASE)
            normalised = normalised.replace("_", " ")
            normalised = re.sub(r'\bMS\b', 'Microsoft', normalised)
            normalised = re.sub(r'\bDC\b', 'Domain Controller', normalised)
            normalised = re.sub(r'\bSERVER\b', 'Windows Server', normalised, flags=re.IGNORECASE)
            pi = detect_benchmark_from_name(normalised)
            if pi.platform:
                platform_info.platform = pi.platform
                platform_info.platform_family = pi.platform_family
                platform_info.os_version = pi.os_version or platform_info.os_version
            if pi.benchmark_name and not platform_info.benchmark_name:
                platform_info.benchmark_name = pi.benchmark_name
                platform_info.benchmark_version = pi.benchmark_version or platform_info.benchmark_version
                platform_info.scheme = pi.scheme or platform_info.scheme

        # ── Build ParsedFinding ───────────────────────────────
        # Split inline Rationale: / Impact: markers from the Info blob
        info_raw = _clean_text(sections.get("info", ""))
        desc, rationale, impact = _split_info_text(info_raw)
        # Prefer separately-extracted sections if the HTML had them as headers
        rationale = _clean_text(sections.get("rationale", "")) or rationale
        impact = _clean_text(sections.get("impact", "")) or impact
        findings.append(ParsedFinding(
            section_number=section_number,
            title=raw_title,
            status=status,
            severity="medium",
            description=desc or None,
            rationale=rationale or None,
            impact=impact or None,
            solution=_clean_text(sections.get("solution", "")) or None,
            see_also=_clean_text(sections.get("see_also", "")) or None,
            policy_value=_clean_text(sections.get("policy_value", "")) or None,
            actual_value=_extract_actual_value(sections.get("hosts", "")) or None,
            framework_mappings=framework_mappings if framework_mappings else None,
        ))

    logger.info("HTML parser: extracted %d findings from %d title bars", len(findings), len(bars))
    return findings


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
