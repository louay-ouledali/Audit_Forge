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
        tmpl = match_template(rule, platform_family)
        if tmpl:
            tmpl["section_number"] = rule.get("section_number", "")
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
        SUB_BATCH_SIZE = 5
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


def _post_process_llm_result(result: dict[str, Any]) -> dict[str, Any]:
    """Clean up common LLM mistakes in generated commands and regex patterns."""
    from backend.core.verification_engine import _check_regex_quality

    regex = result.get("expected_output_regex", "")
    if regex:
        # Check if regex is a bad English-phrase pattern (reuse verification logic)
        quality_error = _check_regex_quality(regex)
        if quality_error:
            # Clear the bad regex so verification falls back to exit-code check
            result["expected_output_regex"] = ""
            logger.warning(
                "Cleared bad LLM regex for %s: %s",
                result.get("section_number", "?"), quality_error,
            )
        else:
            # Validate the regex compiles
            try:
                re.compile(result["expected_output_regex"])
            except re.error:
                logger.warning(
                    "Invalid regex from LLM for %s: %s — clearing",
                    result.get("section_number", "?"),
                    result["expected_output_regex"],
                )
                result["expected_output_regex"] = ""

    return result


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
