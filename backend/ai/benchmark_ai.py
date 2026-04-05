"""AI functions for CIS benchmark Phase 1 parsing and Phase 2 command generation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from backend.ai.llm_manager import llm_manager
from backend.ai.prompts import (
    COMMAND_REGENERATION,
    COMMAND_REGENERATION_SYSTEM,
    PHASE1_CATEGORY_INSTRUCTION,
    PHASE1_CATEGORY_INSTRUCTION_DISABLED,
    PHASE1_METADATA_DETECTION,
    PHASE1_METADATA_SYSTEM,
    PHASE1_RULE_EXTRACTION,
    PHASE1_RULES_SYSTEM,
    PHASE2_COMMAND_GENERATION,
    PHASE2_COMMAND_SYSTEM,
    PHASE3_VALIDATION,
    PHASE3_VALIDATION_SYSTEM,
)
from backend.core.command_templates import match_template

logger = logging.getLogger("auditforge.ai")


async def detect_benchmark_metadata(first_pages_text: str) -> dict[str, Any]:
    """Use LLM to detect benchmark title, version, platform, etc from first pages."""
    prompt = PHASE1_METADATA_DETECTION.format(first_pages_text=first_pages_text)

    # Try up to 2 times — metadata is critical for the benchmark
    for attempt in range(2):
        try:
            result = await llm_manager.invoke_json(
                prompt, system_prompt=PHASE1_METADATA_SYSTEM, timeout=180.0,
                task="phase1_parsing",
            )
            # LLM may return a list wrapping the dict — unwrap it
            if isinstance(result, list):
                result = result[0] if result else {}
            if isinstance(result, str):
                # Try parsing string as JSON (double-encoded)
                import json as _json
                try:
                    result = _json.loads(result)
                except (ValueError, _json.JSONDecodeError):
                    logger.warning("Metadata returned as unparseable string, attempt %d", attempt + 1)
                    if attempt == 0:
                        continue
                    result = {}
            if not isinstance(result, dict):
                logger.warning("LLM returned unexpected type for metadata: %s (attempt %d)", type(result), attempt + 1)
                if attempt == 0:
                    continue
                result = {}
            break
        except Exception as exc:
            logger.warning("Metadata detection attempt %d failed: %s", attempt + 1, exc)
            if attempt == 0:
                continue
            result = {}

    if not isinstance(result, dict):
        result = {}

    # Ensure expected keys are present
    return {
        "title": result.get("title", "Unknown Benchmark"),
        "version": result.get("version", "unknown"),
        "platform": result.get("platform", "unknown"),
        "platform_family": result.get("platform_family", "other"),
        "profiles": result.get("profiles", []),
    }


async def extract_rules_from_section(
    pdf_section_text: str,
    category_detection_enabled: bool = True,
) -> list[dict[str, Any]]:
    """Use LLM to extract structured rules from a PDF section chunk."""
    category_instruction = (
        PHASE1_CATEGORY_INSTRUCTION if category_detection_enabled else PHASE1_CATEGORY_INSTRUCTION_DISABLED
    )
    system_prompt = PHASE1_RULES_SYSTEM.format(category_instruction=category_instruction)
    prompt = PHASE1_RULE_EXTRACTION.format(pdf_section_text=pdf_section_text)
    result = await llm_manager.invoke_json(prompt, system_prompt=system_prompt, timeout=600.0, task="phase1_parsing")
    if isinstance(result, list):
        return result
    # Mistral sometimes wraps the array in a dict like {"rules": [...]}
    if isinstance(result, dict):
        for v in result.values():
            if isinstance(v, list):
                return v
    return []


def _prepare_rule_for_llm(rule: dict[str, Any]) -> dict[str, str]:
    """Prepare a compact rule dict for LLM prompt injection.

    Applies PDF line-break cleanup before truncation so that identifiers
    like registry value names are never sent to the LLM in a broken state.
    """
    from backend.core.command_templates import _fix_line_breaks

    audit_raw = rule.get("audit_description_raw") or ""
    remediation_raw = rule.get("remediation_description_raw") or ""
    # Fix PDF line-break artifacts BEFORE truncating
    audit = _fix_line_breaks(audit_raw)[:600]
    remediation = _fix_line_breaks(remediation_raw)[:400]
    return {
        "section_number": rule.get("section_number", ""),
        "title": rule.get("title", ""),
        "audit": audit if audit else "See remediation.",
        "remediation": remediation if remediation else "N/A",
    }


async def _call_llm_for_batch(
    rules: list[dict[str, Any]],
    platform: str,
    platform_family: str,
) -> list[dict[str, Any]]:
    """Send a batch of rules to the LLM and parse the response."""
    rules_compact = [_prepare_rule_for_llm(r) for r in rules]
    rules_json = json.dumps(rules_compact, indent=1)

    prompt = PHASE2_COMMAND_GENERATION.format(
        platform=platform,
        platform_family=platform_family,
        rules_json=rules_json,
    )
    result = await llm_manager.invoke_json(
        prompt, system_prompt=PHASE2_COMMAND_SYSTEM, timeout=240.0,
        task="phase2_commands",
    )
    # Normalize: ensure we have a list
    if isinstance(result, dict):
        # LLM might wrap in {"rules": [...]} or {"results": [...]}
        for key in ("rules", "results", "data", "commands"):
            if key in result and isinstance(result[key], list):
                result = result[key]
                break
        else:
            # Single object → wrap
            result = [result]
    if not isinstance(result, list):
        return []

    # Normalize each item: ensure string fields, not arrays
    normalized = []
    for item in result:
        if not isinstance(item, dict):
            continue
        clean = {}
        for k, v in item.items():
            if isinstance(v, list):
                # LLM sometimes returns ["cmd1", "cmd2"] — join them
                clean[k] = " ".join(str(x) for x in v)
            elif v is None:
                clean[k] = ""
            else:
                clean[k] = str(v)
        normalized.append(clean)
    return normalized


async def generate_commands_for_batch(
    rules_batch: list[dict[str, Any]],
    platform: str,
    platform_family: str,
    concurrency: int = 3,
) -> list[dict[str, Any]]:
    """Generate audit commands with deterministic templates + concurrent LLM fallback.

    For each rule, first tries the deterministic command-template system
    (instant, no LLM call needed).  Rules that don't match any template
    are batched and sent to the LLM concurrently.

    Returns one result dict per input rule, in the same order.
    """
    # --- Phase A: try deterministic templates first ---
    all_results: list[dict[str, Any] | None] = [None] * len(rules_batch)
    llm_needed: list[tuple[int, dict[str, Any]]] = []  # (original_index, rule)

    for idx, rule in enumerate(rules_batch):
        tmpl = match_template(rule, platform_family, platform=platform)
        if tmpl:
            tmpl["section_number"] = rule.get("section_number", "")
            tmpl["_source"] = "template"
            tmpl["_confidence_score"] = 0.85
            tmpl["_confidence_source"] = "template"
            all_results[idx] = tmpl
            logger.info(
                "Template matched for %s: %s",
                rule.get("section_number", "?"),
                tmpl.get("audit_command", "")[:60],
            )
        else:
            llm_needed.append((idx, rule))

    template_count = len(rules_batch) - len(llm_needed)
    if template_count:
        logger.info(
            "Templates resolved %d/%d rules; %d remaining for LLM",
            template_count, len(rules_batch), len(llm_needed),
        )

    # --- Phase B: send unmatched rules to LLM in concurrent sub-batches ---
    if llm_needed:
        SUB_BATCH_SIZE = 3  # Fewer rules per LLM call = better accuracy
        sub_batches: list[list[tuple[int, dict[str, Any]]]] = []
        for i in range(0, len(llm_needed), SUB_BATCH_SIZE):
            sub_batches.append(llm_needed[i : i + SUB_BATCH_SIZE])

        semaphore = asyncio.Semaphore(concurrency)

        async def _process_sub_batch(
            sb: list[tuple[int, dict[str, Any]]],
        ) -> list[tuple[int, dict[str, Any]]]:
            async with semaphore:
                rules_only = [r for _, r in sb]
                try:
                    raw = await _call_llm_for_batch(rules_only, platform, platform_family)
                    sections_in = [r.get("section_number", "?") for r in rules_only]
                    sections_out = [r.get("section_number", "?") for r in raw if isinstance(r, dict)]
                    cmds_out = [bool(r.get("audit_command")) for r in raw if isinstance(r, dict)]
                    logger.info(
                        "Sub-batch IN=%s OUT=%s has_cmd=%s",
                        sections_in, sections_out, cmds_out,
                    )
                    by_sec: dict[str, dict] = {}
                    for item in raw:
                        if isinstance(item, dict):
                            sec = item.get("section_number", "")
                            if sec:
                                by_sec[sec] = item

                    matched: list[tuple[int, dict[str, Any]]] = []
                    for pos, (orig_idx, rule) in enumerate(sb):
                        sec = rule.get("section_number", "")
                        if sec in by_sec:
                            result = _post_process_llm_result(by_sec[sec])
                            matched.append((orig_idx, result))
                        elif pos < len(raw) and isinstance(raw[pos], dict):
                            result = _post_process_llm_result(raw[pos])
                            matched.append((orig_idx, result))
                        else:
                            matched.append((orig_idx, {}))
                    return matched
                except Exception as exc:
                    sections = [r.get("section_number", "?") for _, r in sb]
                    logger.warning("Sub-batch [%s] failed: %s", ",".join(sections), exc)
                    return [(idx, {}) for idx, _ in sb]

        tasks = [_process_sub_batch(sb) for sb in sub_batches]
        sub_results = await asyncio.gather(*tasks)

        for batch_result in sub_results:
            for orig_idx, result in batch_result:
                all_results[orig_idx] = result

    # Replace any remaining None slots with empty dicts
    return [r if r is not None else {} for r in all_results]


import re as _re

_TRANSPORT_TAG_RE = _re.compile(
    r"^\s*\[(SQL|SHELL|POWERSHELL|CLI|API)\]\s*", _re.IGNORECASE
)

_TRANSPORT_MAP = {
    "sql": "sql",
    "shell": "shell",
    "powershell": "powershell",
    "cli": "cli",
    "api": "api",
}


def _extract_transport_tag(cmd: str) -> tuple[str, str | None]:
    """Strip a [SQL]/[SHELL]/[POWERSHELL]/[CLI] prefix from a command.

    Returns (cleaned_command, transport_value) where transport_value is one of
    "sql", "shell", "powershell", "cli", "api", or None if no tag found.
    """
    m = _TRANSPORT_TAG_RE.match(cmd)
    if m:
        tag = m.group(1).lower()
        return cmd[m.end():], _TRANSPORT_MAP.get(tag)
    return cmd, None


def _post_process_llm_result(result: dict) -> dict:
    """Clean up common LLM mistakes in generated commands and expected output expressions."""
    from backend.core.comparison_engine import validate_expression

    # --- Extract transport tag prefix from command ---
    cmd = result.get("audit_command", "")
    if cmd:
        cmd, transport = _extract_transport_tag(cmd)
        if transport:
            result["command_transport"] = transport

        # Strip shell pipes from SQL transport commands (LLM sometimes appends | grep)
        effective_transport = result.get("command_transport", "")
        if effective_transport == "sql" and re.search(r"\|\s*(?:grep|awk|sed|wc|cut|sort|head|tail|tr)\b", cmd):
            pipe_pos = cmd.find("|")
            if pipe_pos > 0:
                cleaned = cmd[:pipe_pos].rstrip().rstrip(";").rstrip('"').rstrip("'")
                logger.warning(
                    "Stripped shell pipe from SQL command for %s: ...%s",
                    result.get("section_number", "?"), cmd[pipe_pos:pipe_pos+40],
                )
                cmd = cleaned

        # --- Fix commands that test compliance instead of retrieving values ---
        cmd = _fix_compliance_testing_command(cmd)
        cmd = _sanitize_command(cmd)
        result["audit_command"] = cmd

    # --- Fix expected output expression ---
    expr = result.get("expected_output_regex", "")
    if expr:
        # Convert legacy regex patterns to comparison expressions where possible
        expr = _convert_regex_to_expression(expr)
        result["expected_output_regex"] = expr

        # Validate the expression
        error = validate_expression(expr)
        if error:
            # Clear the bad expression so verification falls back to exit-code check
            result["expected_output_regex"] = ""
            logger.warning(
                "Cleared bad LLM expression for %s: %s",
                result.get("section_number", "?"), error,
            )

    # --- Confidence tracking for LLM-generated commands ---
    if "_confidence_score" not in result:
        result["_confidence_score"] = 0.50
        result["_confidence_source"] = "llm_generated"

    return result


def _convert_regex_to_expression(expr: str) -> str:
    """Convert common regex patterns to comparison expressions.

    This handles the case where the LLM still produces regex despite
    being instructed to use comparison expressions.
    """
    stripped = expr.strip()

    # Already a comparison expression — leave it alone
    if re.match(r'^(>=|<=|!=|==|>|<)\s*\S', stripped):
        return stripped
    if re.match(r'^(contains|regex):', stripped, re.IGNORECASE):
        return stripped

    # ^1$ → ==1, ^0$ → ==0, ^Disabled$ → ==Disabled, etc.
    exact_match = re.match(r'^\^([^$\\[\]()|*+?{}]+)\$$', stripped)
    if exact_match:
        value = exact_match.group(1)
        # Only convert if it's a simple value (no regex metacharacters)
        if not re.search(r'[\\[\]()|*+?{}]', value):
            return f"=={value}"

    # Complex numeric regex patterns like ^(?:1[4-9]|[2-9]\d|\d{3,})$ → hard to reverse
    # Leave these as regex: prefix for backward compatibility
    if re.match(r'^\^\(\?:', stripped):
        return f"regex:{stripped}"

    # Reject obvious English prose BEFORE converting to contains:
    _english = [
        r'^\d+\s+or\s+(?:more|fewer|greater|less)',
        r'(?:should|must|needs?\s+to)\b',
        r'\bshould\s+be\b',
        r'\bor\s+(?:higher|lower|above|below)\b',
        r'\bat\s+least\s+\d+',
        r'\bno\s+more\s+than\b',
        r'\bgreater\s+than\b',
        r'\bless\s+than\b',
        r'enabled\s+or\s+greater',
    ]
    for pat in _english:
        if re.search(pat, stripped, re.IGNORECASE):
            return stripped  # Leave as-is so validate_expression rejects it

    # Simple patterns like "Success and Failure" → contains:Success and Failure
    if not re.search(r'[\\^$*+?{}()\[\]|]', stripped) and len(stripped) > 3:
        return f"contains:{stripped}"

    return stripped


# Patterns that indicate the command is testing compliance rather than retrieving a value
_COMPLIANCE_TEST_PATTERNS = [
    # PowerShell if/else blocks
    re.compile(r'\bif\s*\(.*-(?:ge|le|gt|lt|eq|ne)\b', re.IGNORECASE),
    # PowerShell ternary-style pass/fail
    re.compile(r'["\'](?:PASS|FAIL|Compliant|Non-compliant)["\']', re.IGNORECASE),
    # Bash test constructs
    re.compile(r'\btest\s+.*(?:&&|;\s*then)\b'),
    # Bash if/then blocks
    re.compile(r'\bif\s+\[.*\]\s*;\s*then\b'),
    # echo PASS/FAIL pattern
    re.compile(r'\becho\s+["\']?(?:PASS|FAIL|Compliant)["\']?\b', re.IGNORECASE),
]


def _fix_compliance_testing_command(cmd: str) -> str:
    """Strip compliance-testing logic from commands, keeping only the retrieval part.

    Also converts multi-value commands to single-value extraction where
    possible.
    """
    if not cmd:
        return cmd

    # Check if command contains compliance-testing patterns
    has_compliance_test = any(p.search(cmd) for p in _COMPLIANCE_TEST_PATTERNS)
    if not has_compliance_test:
        return cmd

    # Try to extract the underlying retrieval command
    original = cmd

    # Pattern: "net accounts" somewhere in a larger if/else block
    # Extract just the relevant Select-String line if possible
    net_field_match = re.search(
        r"net\s+accounts.*Select-String\s+['\"]([^'\"]+)['\"]",
        cmd, re.IGNORECASE,
    )
    if net_field_match:
        field = net_field_match.group(1)
        cmd = f"(net accounts | Select-String '{field}').Line -replace '\\D',''"
    elif re.search(r'\bnet\s+accounts\b', cmd, re.IGNORECASE):
        cmd = "net accounts"

    # Pattern: Get-ItemProperty extraction wrapped in if/else
    gip_match = re.search(
        r"\(Get-ItemProperty\s+-Path\s+'([^']+)'\s+-Name\s+'?(\w+)'?\)\.(\w+)",
        cmd, re.IGNORECASE,
    )
    if gip_match:
        path, name, prop = gip_match.group(1), gip_match.group(2), gip_match.group(3)
        cmd = f"(Get-ItemProperty -Path '{path}' -Name '{name}').{prop}"

    # Pattern: "reg query HKLM\..." somewhere in a larger if/else block
    # Convert to Get-ItemProperty for single-value output
    reg_match = re.search(
        r'reg\s+query\s+(HKLM\\[^\s|;"]+)\s+/v\s+(\S+)',
        cmd, re.IGNORECASE,
    )
    if reg_match:
        key_path = reg_match.group(1)
        value_name = reg_match.group(2)
        ps_path = key_path.replace("HKLM\\", "HKLM:\\", 1)
        cmd = f"(Get-ItemProperty -Path '{ps_path}' -Name '{value_name}').{value_name}"

    # Pattern: "sysctl ..." in a test block — use -n for value only
    sysctl_match = re.search(r'sysctl\s+(?:-n\s+)?([\w.]+)', cmd)
    if sysctl_match:
        param = sysctl_match.group(1)
        cmd = f"sysctl -n {param}"

    # Pattern: "systemctl is-enabled ..." in a test block
    systemctl_match = re.search(r'(systemctl\s+is-enabled\s+[\w@.-]+)', cmd)
    if systemctl_match:
        cmd = systemctl_match.group(1) + " 2>/dev/null || echo not-found"

    # Pattern: "auditpol /get ..." in a test block
    auditpol_match = re.search(r'(auditpol\s+/get\s+/subcategory:\S+)', cmd)
    if auditpol_match:
        cmd = auditpol_match.group(1)

    # Pattern: "grep ..." in a test block
    grep_match = re.search(
        r"""(grep\s+(?:-[A-Za-z]+\s+)?(?:'[^']+'|"[^"]+"|[\w^$.\\]+)\s+/[\w/._-]+)""",
        cmd,
    )
    if grep_match:
        cmd = grep_match.group(1)

    if cmd != original:
        logger.info(
            "Fixed compliance-testing command → single-value retrieval: %s",
            cmd[:80],
        )

    return cmd


# ── Patterns that indicate an enforcement/write command rather than an audit/read ──
_ENFORCEMENT_PATTERNS = [
    re.compile(r'\bSet-ItemProperty\b', re.IGNORECASE),
    re.compile(r'\bNew-ItemProperty\b', re.IGNORECASE),
    re.compile(r'\bRemove-ItemProperty\b', re.IGNORECASE),
    re.compile(r'\bRemove-Item\b', re.IGNORECASE),
    re.compile(r'\breg\s+add\b', re.IGNORECASE),
    re.compile(r'\breg\s+delete\b', re.IGNORECASE),
    re.compile(r'\bSet-Service\b', re.IGNORECASE),
    re.compile(r'\bStop-Service\b', re.IGNORECASE),
    re.compile(r'\bDisable-Service\b', re.IGNORECASE),
    re.compile(r'\bEnable-NetFirewallRule\b', re.IGNORECASE),
    re.compile(r'\bSet-NetFirewall\w+\b', re.IGNORECASE),
    re.compile(r'\bSet-MpPreference\b', re.IGNORECASE),
    re.compile(r'\bsecedit\s+/configure\b', re.IGNORECASE),
    re.compile(r'\bnet\s+user\b', re.IGNORECASE),
    re.compile(r'\bnet\s+localgroup\b', re.IGNORECASE),
    re.compile(r'\bchmod\b'),
    re.compile(r'\bchown\b'),
    re.compile(r'\busermod\b'),
    re.compile(r'\bsed\s+-i\b'),
    re.compile(r'\bapt\s+(?:install|remove)\b'),
    re.compile(r'\byum\s+(?:install|remove|erase)\b'),
    re.compile(r'\bsystemctl\s+(?:enable|disable|stop|start|mask)\b'),
]

# ── Patterns that indicate syntactically broken PowerShell ──
_BAD_SYNTAX_PATTERNS = [
    re.compile(r'\s&&\s'),         # Bash operator in PowerShell
    re.compile(r'^\s*\|\s'),       # Leading pipe with nothing before it
    re.compile(r'\{\s*$'),         # Unclosed script block at end of line
]


def _sanitize_command(cmd: str) -> str:
    """Sanitize a generated audit command.

    Catches and fixes several common LLM mistakes:
    1. Enforcement/write commands (Set-ItemProperty etc.) → clear
    2. Bash operators in PowerShell (&&) → semicolons
    3. Multi-statement Write-Host epilogues → strip
    4. Overly long commands → truncate to the retrieval core
    """
    if not cmd or not cmd.strip():
        return cmd

    original = cmd

    # ── 1. Reject enforcement commands ──
    for pat in _ENFORCEMENT_PATTERNS:
        if pat.search(cmd):
            # Try to find and extract a read-only part before the write
            # e.g., "Get-ItemProperty ... ; Set-ItemProperty ..."
            parts = re.split(r'\s*;\s*', cmd)
            read_parts = [p for p in parts if not any(ep.search(p) for ep in _ENFORCEMENT_PATTERNS)]
            if read_parts:
                cmd = "; ".join(read_parts)
                logger.warning("Stripped enforcement commands, keeping: %s", cmd[:80])
                break
            else:
                logger.warning("Rejected enforcement-only command: %s", cmd[:80])
                return ""

    # ── 2. Fix bash && operator → PowerShell semicolons ──
    cmd = re.sub(r'\s*&&\s*', '; ', cmd)

    # ── 3. Strip trailing Write-Host / echo statements ──
    cmd = re.sub(r'\s*;\s*Write-Host\s+.*$', '', cmd, flags=re.IGNORECASE)
    cmd = re.sub(r'\s*;\s*echo\s+["\'](?:PASS|FAIL|Compliant|Non-Compliant)["\'].*$', '', cmd, flags=re.IGNORECASE)

    # ── 4. Strip enclosing try/catch blocks ──
    try_match = re.match(r'^\s*try\s*\{(.+)\}\s*catch\s*\{.*\}\s*$', cmd, re.DOTALL | re.IGNORECASE)
    if try_match:
        inner = try_match.group(1).strip()
        if inner:
            cmd = inner

    # ── 5. Trim excessive whitespace and newlines ──
    cmd = re.sub(r'\s+', ' ', cmd).strip()

    # ── 6. Detect LLM garbage in grep/awk patterns ──
    # The LLM sometimes dumps remediation prose into the regex pattern,
    # producing commands like:  grep -E 'hostbasedauthentication\n\nhostbased...- IF - Match set'
    # Detect multi-line literals (\n), long prose, or dangerous regex fragments.
    grep_match = re.search(r"""(?:grep|egrep|awk)\s+(?:-[A-Za-z]+\s+)*['"](.+?)['"]""", cmd)
    if grep_match:
        pattern_text = grep_match.group(1)
        # Flag 1: literal \n in pattern (LLM dumped multi-line text)
        if r'\n' in pattern_text and len(pattern_text) > 60:
            logger.warning("Rejected grep with multi-line LLM garbage: %s", cmd[:100])
            return ""
        # Flag 2: English prose fragments that are never valid regex
        _PROSE_MARKERS = [
            " IF ", " Match set", " Edit ", " remediation",
            " should be ", " must be ", " ensure that ", " configure ",
            " the following ", " by default",
        ]
        if any(marker.lower() in pattern_text.lower() for marker in _PROSE_MARKERS):
            logger.warning("Rejected grep with remediation prose: %s", cmd[:100])
            return ""
        # Flag 3: Extremely long pattern (>150 chars) — almost certainly junk
        if len(pattern_text) > 150:
            logger.warning("Rejected grep with excessively long pattern (%d chars): %s",
                          len(pattern_text), cmd[:100])
            return ""

    # ── 7. Reject echo/Write-Output stub commands ──
    cmd_lower = cmd.lower().strip()
    _STUB_KEYWORDS = ("manual", "not-auditable", "not auditable", "physical inspection",
                      "requires manual", "cannot be automated", "manual verification")
    if cmd_lower.startswith(("echo ", "write-output ", "write-host ")):
        if any(kw in cmd_lower for kw in _STUB_KEYWORDS):
            logger.warning("Rejected stub/manual-check command: %s", cmd[:80])
            return ""

    if cmd != original:
        logger.info("Sanitized command: %s", cmd[:100])

    return cmd


async def validate_commands_batch(
    rules_with_commands: list[dict[str, Any]],
    platform: str,
    platform_family: str,
) -> list[dict[str, Any]]:
    """Validate a batch of rules + generated commands via LLM (Phase 3).

    Each item in rules_with_commands should have:
      section_number, title, audit_description_raw,
      audit_command, expected_output_regex, expected_output_description

    Returns a list of validation results, one per rule.
    """
    # Build compact representation for the LLM
    compact = []
    for r in rules_with_commands:
        from backend.core.command_templates import _fix_line_breaks
        audit_raw = r.get("audit_description_raw") or ""
        audit = _fix_line_breaks(audit_raw)[:500]
        compact.append({
            "section_number": r.get("section_number", ""),
            "title": r.get("title", ""),
            "audit_instructions": audit if audit else "See remediation.",
            "audit_command": r.get("audit_command", ""),
            "expected_output_regex": r.get("expected_output_regex", ""),
            "expected_output_description": r.get("expected_output_description", ""),
        })

    rules_json = json.dumps(compact, indent=1)
    prompt = PHASE3_VALIDATION.format(
        platform=platform,
        platform_family=platform_family,
        rules_json=rules_json,
    )

    result = await llm_manager.invoke_json(
        prompt,
        system_prompt=PHASE3_VALIDATION_SYSTEM,
        timeout=300.0,
        task="phase3_validation",
    )

    # Normalize response
    if isinstance(result, dict):
        for key in ("results", "rules", "data", "validations"):
            if key in result and isinstance(result[key], list):
                result = result[key]
                break
        else:
            result = [result]
    if not isinstance(result, list):
        return []

    # Normalize each item
    normalized = []
    for item in result:
        if not isinstance(item, dict):
            continue
        # Ensure corrections is always a list
        corr = item.get("corrections", [])
        if not isinstance(corr, list):
            corr = []
        # Validate each correction has required fields
        clean_corr = []
        for c in corr:
            if isinstance(c, dict) and c.get("field") and c.get("new_value") is not None:
                clean_corr.append({
                    "field": str(c["field"]),
                    "old_value": str(c.get("old_value", "")),
                    "new_value": str(c["new_value"]),
                    "reason": str(c.get("reason", "")),
                })
        normalized.append({
            "section_number": str(item.get("section_number", "")),
            "status": str(item.get("status", "validated")),
            "confidence": str(item.get("confidence", "medium")),
            "corrections": clean_corr,
            "notes": str(item.get("notes", "")),
        })

    return normalized


async def regenerate_command(
    *,
    section_number: str,
    title: str,
    platform: str,
    platform_family: str,
    assessment_type: str | None,
    audit_description_raw: str | None,
    remediation_description_raw: str | None,
    current_audit_command: str | None,
    current_expected_output_regex: str | None,
    flag_reason: str,
    flag_error_output: str | None = None,
    system_info: str | None = None,
    previous_commands: list[dict[str, Any]] | None = None,
    connection_method: str | None = None,
    command_transport: str | None = None,
) -> dict[str, Any]:
    """Use LLM to regenerate a failed audit command with context."""
    error_section = ""
    if flag_error_output:
        error_section = f"ERROR OUTPUT FROM EXECUTION:\n{flag_error_output}"

    system_info_section = ""
    if system_info:
        system_info_section = f"TARGET SYSTEM INFO:\n{system_info}"

    history_section = ""
    if previous_commands:
        history_lines = []
        for i, prev in enumerate(previous_commands, 1):
            cmd = prev.get("audit_command", "N/A")
            reason = prev.get("flag_reason", "N/A")
            history_lines.append(f"Attempt {i}: {cmd}\n  Failure: {reason}")
        history_section = "PREVIOUS FAILED ATTEMPTS:\n" + "\n".join(history_lines)

    prompt = COMMAND_REGENERATION.format(
        section_number=section_number,
        title=title,
        platform=platform,
        platform_family=platform_family,
        assessment_type=assessment_type or "automated",
        connection_method=connection_method or "N/A",
        command_transport=command_transport or "N/A",
        audit_description_raw=audit_description_raw or "N/A",
        remediation_description_raw=remediation_description_raw or "N/A",
        current_audit_command=current_audit_command or "N/A",
        current_expected_output_regex=current_expected_output_regex or "N/A",
        flag_reason=flag_reason,
        error_section=error_section,
        system_info_section=system_info_section,
        history_section=history_section,
    )
    system_prompt = COMMAND_REGENERATION_SYSTEM
    result = await llm_manager.invoke_json(prompt, system_prompt=system_prompt, timeout=120.0, task="phase2_commands")
    if isinstance(result, dict):
        return result
    return {}
