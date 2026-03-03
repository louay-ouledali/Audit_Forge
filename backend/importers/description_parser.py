"""Nessus Description mega-field parser.

Extracts structured data from the Nessus 'Description' column, which contains
a monolithic text block with embedded labeled sections.

Real-world format (validated against nessus_report.csv, 431 rows):
───────────────────────────────────────────────────────────────
"2.2.3 Ensure 'Access this computer from the network' is set to ..." : [FAILED]

Description text here...

Rationale:
More text...

Impact:
Optional impact text...

Solution:
Fix instructions...

Default Value:
Optional default value...

See Also:
https://workbench.cisecurity.org/...

Reference:
800-171|3.1.1,800-53|AC-3,CSCv7|14.6,CSF|PR.AC-4,...

Policy Value:
'Administrators' && 'Authenticated Users'

Actual Value:
'enterprise domain controllers' && 'administrators' && ...
───────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("auditforge.importers.description_parser")

# Section headers we look for, in typical order of appearance.
# We match case-insensitively with optional colon suffix.
_SECTION_PATTERNS: list[tuple[str, str]] = [
    ("description", r"^(.*?)(?=\n\s*(?:Rationale|Impact|Solution|Default\s*Value|See\s*Also|Reference|Policy\s*Value|Actual\s*Value)\s*:|\Z)"),
    ("rationale", r"Rationale\s*:\s*\n(.*?)(?=\n\s*(?:Impact|Solution|Default\s*Value|See\s*Also|Reference|Policy\s*Value|Actual\s*Value)\s*:|\Z)"),
    ("impact", r"Impact\s*:\s*\n(.*?)(?=\n\s*(?:Solution|Default\s*Value|See\s*Also|Reference|Policy\s*Value|Actual\s*Value)\s*:|\Z)"),
    ("solution", r"Solution\s*:\s*\n(.*?)(?=\n\s*(?:Default\s*Value|See\s*Also|Reference|Policy\s*Value|Actual\s*Value)\s*:|\Z)"),
    ("default_value", r"Default\s*Value\s*:\s*\n(.*?)(?=\n\s*(?:See\s*Also|Reference|Policy\s*Value|Actual\s*Value)\s*:|\Z)"),
    ("see_also", r"See\s*Also\s*:\s*\n(.*?)(?=\n\s*(?:Reference|Policy\s*Value|Actual\s*Value)\s*:|\Z)"),
    ("reference", r"Reference\s*:\s*\n(.*?)(?=\n\s*(?:Policy\s*Value|Actual\s*Value)\s*:|\Z)"),
    ("policy_value", r"Policy\s*Value\s*:\s*\n(.*?)(?=\n\s*Actual\s*Value\s*:|\Z)"),
    ("actual_value", r"Actual\s*Value\s*:\s*\n(.*)"),
]

# Pre-compiled section-splitting regex.
# Splits on known section headers, keeping the header as a delimiter.
_SPLIT_RE = re.compile(
    r"\n\s*(?=(?:Rationale|Impact|Solution|Default\s+Value|See\s+Also|Reference|Policy\s+Value|Actual\s+Value)\s*:)",
    re.IGNORECASE,
)


def parse_description(raw: str) -> dict[str, Any]:
    """Parse a Nessus Description mega-field into structured sections.

    Parameters
    ----------
    raw : str
        The raw Description column value from a Nessus CSV row.

    Returns
    -------
    dict with keys:
        title, status, description, rationale, impact, solution,
        default_value, see_also, reference_raw, policy_value, actual_value,
        framework_mappings (dict[str, list[str]])
    """
    if not raw or not raw.strip():
        return {}

    result: dict[str, Any] = {
        "title": "",
        "status": "",
        "description": "",
        "rationale": "",
        "impact": "",
        "solution": "",
        "default_value": "",
        "see_also": "",
        "reference_raw": "",
        "policy_value": "",
        "actual_value": "",
        "framework_mappings": {},
        "section_number": "",
    }

    text = raw.strip()

    # ── Extract title + status from first line ──────────────────
    # Format: "2.2.3 Ensure 'Access this computer ...' is set to ..." : [FAILED]
    # Or:     "1.1.1 Some title" : [PASSED]
    first_line_match = re.match(
        r'^["\']?\s*([\d.]+(?:\.\d+)*)\s+(.*?)\s*["\']?\s*:\s*\[(\w+)\]',
        text,
    )
    if first_line_match:
        result["section_number"] = first_line_match.group(1)
        result["title"] = first_line_match.group(2).strip().strip("'\"")
        result["status"] = first_line_match.group(3).upper()
        # Remove first line from remaining text
        text = text[first_line_match.end():].strip()
    else:
        # Try without status bracket
        title_match = re.match(r'^["\']?\s*([\d.]+(?:\.\d+)*)\s+(.*?)(?:\n|$)', text)
        if title_match:
            result["section_number"] = title_match.group(1)
            result["title"] = title_match.group(2).strip().strip("'\"")
            text = text[title_match.end():].strip()

    # ── Split into sections using headers ───────────────────────
    sections = _split_into_sections(text)

    for key in ["description", "rationale", "impact", "solution", "default_value",
                "see_also", "policy_value", "actual_value"]:
        if key in sections:
            result[key] = sections[key].strip()

    if "reference" in sections:
        result["reference_raw"] = sections["reference"].strip()
        result["framework_mappings"] = parse_references(sections["reference"])

    return result


def _split_into_sections(text: str) -> dict[str, str]:
    """Split raw text into labeled sections using header detection."""
    sections: dict[str, str] = {}

    # Known section headers and their normalized keys
    header_map = {
        "rationale": "rationale",
        "impact": "impact",
        "solution": "solution",
        "default value": "default_value",
        "see also": "see_also",
        "reference": "reference",
        "policy value": "policy_value",
        "actual value": "actual_value",
    }

    # Split by lines that look like section headers
    header_re = re.compile(
        r"^\s*(Rationale|Impact|Solution|Default\s+Value|See\s+Also|Reference|Policy\s+Value|Actual\s+Value)\s*:\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    parts = header_re.split(text)

    # parts[0] is content before the first header → "description"
    if parts:
        sections["description"] = parts[0].strip()

    # Remaining parts alternate: header, content, header, content, ...
    i = 1
    while i < len(parts) - 1:
        header_text = parts[i].strip().lower()
        content = parts[i + 1] if i + 1 < len(parts) else ""
        key = header_map.get(header_text, header_text.replace(" ", "_"))
        sections[key] = content.strip()
        i += 2

    return sections


def parse_references(raw_refs: str) -> dict[str, list[str]]:
    """Parse reference codes into framework → controls mapping.

    Input format (comma-separated):
        800-171|3.1.1,800-53|AC-3,CSCv7|14.6,CSF|PR.AC-4,
        GDPR|32.1.b,HIPAA|164.306(a)(1),LEVEL|1A,...

    Returns:
        {
            "NIST_800_171": ["3.1.1"],
            "NIST_800_53": ["AC-3"],
            "CIS_v7": ["14.6"],
            "NIST_CSF": ["PR.AC-4"],
            "GDPR": ["32.1.b"],
            "HIPAA": ["164.306(a)(1)"],
            "LEVEL": ["1A"],
            ...
        }
    """
    if not raw_refs:
        return {}

    mappings: dict[str, list[str]] = {}

    # Normalize known framework prefixes
    framework_aliases: dict[str, str] = {
        "800-171": "NIST_800_171",
        "800-53": "NIST_800_53",
        "800-53r5": "NIST_800_53r5",
        "cscv6": "CIS_v6",
        "cscv7": "CIS_v7",
        "cscv8": "CIS_v8",
        "csf": "NIST_CSF",
        "csf2.0": "NIST_CSF_v2",
        "gdpr": "GDPR",
        "hipaa": "HIPAA",
        "iso/iec 27001": "ISO_27001",
        "itsg-33": "ITSG_33",
        "level": "LEVEL",
        "nesa": "NESA",
        "qcsc-v1": "QCSC",
        "swift-cscf-v1": "SWIFT",
    }

    # Split on comma, handling potential whitespace
    entries = [e.strip() for e in raw_refs.split(",") if e.strip()]

    for entry in entries:
        if "|" not in entry:
            continue
        parts = entry.split("|", 1)
        if len(parts) != 2:
            continue

        framework_raw = parts[0].strip()
        control = parts[1].strip()

        # Normalize framework name
        framework = framework_aliases.get(framework_raw.lower(), framework_raw.upper())

        if framework not in mappings:
            mappings[framework] = []
        if control and control not in mappings[framework]:
            mappings[framework].append(control)

    return mappings


def extract_profile_level(framework_mappings: dict[str, list[str]]) -> str:
    """Extract profile level (L1/L2) from the LEVEL reference code.

    LEVEL|1A  → "Level 1"
    LEVEL|2S  → "Level 2"
    LEVEL|1MS → "Level 1 - Member Server"
    """
    levels = framework_mappings.get("LEVEL", [])
    if not levels:
        return ""

    level_str = levels[0]

    if level_str.startswith("1"):
        base = "Level 1"
    elif level_str.startswith("2"):
        base = "Level 2"
    else:
        return f"Level {level_str}"

    # Parse sub-type
    suffix = level_str[1:].upper()
    sub_map = {
        "A": "",
        "S": "",
        "MS": " - Member Server",
        "DC": " - Domain Controller",
        "NG": " - Next Generation",
    }
    sub = sub_map.get(suffix, "")
    return f"{base}{sub}"
