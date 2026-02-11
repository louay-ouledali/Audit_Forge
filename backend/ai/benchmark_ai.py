"""AI functions for CIS benchmark Phase 1 parsing and Phase 2 command generation."""

from __future__ import annotations

import asyncio
import json
import logging
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
)

logger = logging.getLogger("auditforge.ai")


async def detect_benchmark_metadata(first_pages_text: str) -> dict[str, Any]:
    """Use LLM to detect benchmark title, version, platform, etc from first pages."""
    prompt = PHASE1_METADATA_DETECTION.format(first_pages_text=first_pages_text)

    # Try up to 2 times — metadata is critical for the benchmark
    for attempt in range(2):
        try:
            result = await llm_manager.invoke_json(
                prompt, system_prompt=PHASE1_METADATA_SYSTEM, timeout=180.0,
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
    result = await llm_manager.invoke_json(prompt, system_prompt=system_prompt, timeout=600.0)
    if isinstance(result, list):
        return result
    # Mistral sometimes wraps the array in a dict like {"rules": [...]}
    if isinstance(result, dict):
        for v in result.values():
            if isinstance(v, list):
                return v
    return []


def _prepare_rule_for_llm(rule: dict[str, Any]) -> dict[str, str]:
    """Prepare a compact rule dict for LLM prompt injection."""
    audit = (rule.get("audit_description_raw") or "")[:600]
    remediation = (rule.get("remediation_description_raw") or "")[:400]
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
    """Generate audit commands with concurrent LLM calls.
    
    Splits rules_batch into sub-batches of ~5 rules, fires them
    concurrently (up to `concurrency` at a time), then merges results
    back in order.
    """
    SUB_BATCH_SIZE = 5
    sub_batches: list[list[dict[str, Any]]] = []
    for i in range(0, len(rules_batch), SUB_BATCH_SIZE):
        sub_batches.append(rules_batch[i : i + SUB_BATCH_SIZE])

    semaphore = asyncio.Semaphore(concurrency)

    async def _process_sub_batch(sb: list[dict[str, Any]]) -> list[dict[str, Any]]:
        async with semaphore:
            try:
                raw = await _call_llm_for_batch(sb, platform, platform_family)
                sections_in = [r.get("section_number", "?") for r in sb]
                sections_out = [r.get("section_number", "?") for r in raw if isinstance(r, dict)]
                cmds_out = [bool(r.get("audit_command")) for r in raw if isinstance(r, dict)]
                logger.info(
                    "Sub-batch IN=%s OUT=%s has_cmd=%s",
                    sections_in, sections_out, cmds_out,
                )
                # Build lookup by section_number for bonus matching
                by_sec: dict[str, dict] = {}
                for item in raw:
                    if isinstance(item, dict):
                        sec = item.get("section_number", "")
                        if sec:
                            by_sec[sec] = item

                matched: list[dict[str, Any]] = []
                for idx, rule in enumerate(sb):
                    sec = rule.get("section_number", "")
                    # Try section_number match first
                    if sec in by_sec:
                        matched.append(by_sec[sec])
                    # Positional fallback (always, not just when lengths match)
                    elif idx < len(raw) and isinstance(raw[idx], dict):
                        matched.append(raw[idx])
                    else:
                        matched.append({})
                return matched
            except Exception as exc:
                sections = [r.get("section_number", "?") for r in sb]
                logger.warning("Sub-batch [%s] failed: %s", ",".join(sections), exc)
                return [{} for _ in sb]

    tasks = [_process_sub_batch(sb) for sb in sub_batches]
    sub_results = await asyncio.gather(*tasks)

    # Flatten in order
    all_results: list[dict[str, Any]] = []
    for sr in sub_results:
        all_results.extend(sr)
    return all_results


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
    result = await llm_manager.invoke_json(prompt, system_prompt=system_prompt, timeout=120.0)
    if isinstance(result, dict):
        return result
    return {}
