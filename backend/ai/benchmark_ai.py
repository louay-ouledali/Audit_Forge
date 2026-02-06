"""AI functions for CIS benchmark Phase 1 parsing and Phase 2 command generation."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.ai.llm_manager import llm_manager
from backend.ai.prompts import (
    COMMAND_REGENERATION,
    PHASE1_CATEGORY_INSTRUCTION,
    PHASE1_CATEGORY_INSTRUCTION_DISABLED,
    PHASE1_METADATA_DETECTION,
    PHASE1_RULE_EXTRACTION,
    PHASE2_COMMAND_GENERATION,
)

logger = logging.getLogger("auditforge.ai")


async def detect_benchmark_metadata(first_pages_text: str) -> dict[str, Any]:
    """Use LLM to detect benchmark title, version, platform, etc from first pages."""
    prompt = PHASE1_METADATA_DETECTION.format(first_pages_text=first_pages_text)
    result = await llm_manager.invoke_json(prompt, timeout=120.0)
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
    prompt = PHASE1_RULE_EXTRACTION.format(
        pdf_section_text=pdf_section_text,
        category_instruction=category_instruction,
    )
    result = await llm_manager.invoke_json(prompt, timeout=300.0)
    if isinstance(result, list):
        return result
    return []


async def generate_commands_for_batch(
    rules_batch: list[dict[str, Any]],
    platform: str,
    platform_family: str,
) -> list[dict[str, Any]]:
    """Use LLM to generate audit commands for a batch of rules (up to 10)."""
    rules_json = json.dumps(rules_batch, indent=2)
    prompt = PHASE2_COMMAND_GENERATION.format(
        platform=platform,
        platform_family=platform_family,
        rules_json=rules_json,
    )
    result = await llm_manager.invoke_json(prompt, timeout=600.0)
    if isinstance(result, list):
        return result
    return []


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
    result = await llm_manager.invoke_json(prompt, timeout=300.0)
    if isinstance(result, dict):
        return result
    return {}
