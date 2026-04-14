"""Format detection for network device configuration files.

Uses scored heuristics on the first 500 lines to identify the vendor/platform
without any LLM dependency.
"""

from __future__ import annotations

import re


def detect_config_format(raw_text: str) -> str:
    """Detect the format of a network device configuration file.

    Returns one of: ``"ios"``, ``"fortios"``, ``"panos_xml"``, ``"junos"``,
    ``"checkpoint"``, ``"pfsense_xml"``, ``"unknown"``.
    """
    if not raw_text or not raw_text.strip():
        return "unknown"

    lines = raw_text.splitlines()[:500]
    text_block = "\n".join(lines)

    # ── 1. XML-based formats (check first — unambiguous) ──────
    stripped_start = raw_text.lstrip()
    if stripped_start.startswith("<?xml") or stripped_start.startswith("<"):
        lower = text_block.lower()
        if "<pfsense>" in lower:
            return "pfsense_xml"
        if any(kw in lower for kw in ("<config version=", "<devices>", "<paloalto>")):
            return "panos_xml"
        # Could be some other XML config; fall through to other checks
        # but if it's clearly XML, mark as unknown_xml later

    # ── 2. FortiOS (config ... end blocks with set statements) ─
    forti_score = 0
    has_config_block = False
    has_set_stmt = False
    has_end_stmt = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("config ") and not stripped.startswith("config-"):
            has_config_block = True
            forti_score += 1
        if stripped.startswith("set "):
            has_set_stmt = True
        if stripped == "end":
            has_end_stmt = True
            forti_score += 1
        if stripped.startswith("next"):
            forti_score += 1
        if "fortinet" in stripped.lower() or "fortigate" in stripped.lower():
            forti_score += 5
    if has_config_block and has_set_stmt and has_end_stmt and forti_score >= 4:
        return "fortios"

    # ── 3. Check Point Gaia (set-command style) ───────────────
    cp_score = 0
    for line in lines:
        stripped = line.strip()
        if re.match(r"^set password-controls ", stripped):
            cp_score += 3
        elif re.match(r"^set interface ", stripped):
            cp_score += 1
        elif re.match(r"^set user ", stripped):
            cp_score += 1
        elif re.match(r"^set hostname ", stripped):
            cp_score += 1
        elif re.match(r"^set timezone ", stripped):
            cp_score += 1
        elif re.match(r"^set static-route ", stripped):
            cp_score += 1
        if "check point" in stripped.lower() or "gaia" in stripped.lower():
            cp_score += 5
    # CP configs are also set-based but don't have config...end blocks
    if cp_score >= 4 and not has_config_block:
        return "checkpoint"

    # ── 4. JunOS brace format ─────────────────────────────────
    junos_brace_score = 0
    for line in lines:
        stripped = line.rstrip()
        if re.match(r"^(system|interfaces|security|protocols|routing-options|firewall|policy-options)\s*\{", stripped):
            junos_brace_score += 3
        elif stripped.endswith("{") and not stripped.startswith("config "):
            junos_brace_score += 1
        if "juniper" in stripped.lower() or "junos" in stripped.lower():
            junos_brace_score += 5
    # Brace-format JunOS has many levels of nested braces
    brace_count = text_block.count("{")
    close_brace_count = text_block.count("}")
    if junos_brace_score >= 4 and brace_count >= 5 and abs(brace_count - close_brace_count) <= 2:
        return "junos"

    # ── 5. JunOS set format (no braces) ──────────────────────
    junos_set_score = 0
    for line in lines:
        stripped = line.strip()
        if re.match(r"^set (system|interfaces|security|protocols|routing-options|firewall|policy-options)\s", stripped):
            junos_set_score += 2
    if junos_set_score >= 6:
        return "junos"

    # ── 6. IOS/ASA/NX-OS (! separators, indented subcmds) ────
    ios_score = 0
    bang_lines = 0
    for line in lines:
        if line.strip() == "!":
            bang_lines += 1
        if re.match(r"^hostname\s+\S", line):
            ios_score += 3
        elif re.match(r"^interface\s+\S", line):
            ios_score += 2
        elif re.match(r"^(router|ip route|access-list|crypto|class-map|policy-map)\s", line):
            ios_score += 1
        elif re.match(r"^!\s*$", line):
            ios_score += 0.5
        if "cisco" in line.lower() or "ios" in line.lower():
            ios_score += 3
    if ios_score >= 5 and bang_lines >= 3:
        return "ios"

    # ── 7. XML fallback ───────────────────────────────────────
    if stripped_start.startswith("<?xml") or stripped_start.startswith("<"):
        return "unknown"

    return "unknown"
