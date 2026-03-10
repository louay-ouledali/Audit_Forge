"""Unknown benchmark parser — LLM-driven reverse engineering for unrecognised file formats.

When Smart Import cannot identify a file format via deterministic detection,
this module uses the LLM to:

1. **Detect the platform** (OS, version, family) from the document content.
2. **Extract security rules** (section numbers, titles, descriptions, severities)
   into the standard ``ExtractedRule`` format.
3. **Cross-match against the command cache** using strict platform equality.

The pipeline is intentionally conservative — confidence thresholds are lower,
and all extracted rules default to ``framework="custom"`` until verified.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.ai.llm_manager import llm_manager
from backend.ai.prompts import (
    UNKNOWN_PLATFORM_DETECTION,
    UNKNOWN_PLATFORM_SYSTEM,
    UNKNOWN_RULE_EXTRACTION,
    UNKNOWN_RULE_SYSTEM,
)
from backend.importers.base import ExtractedRule, PlatformInfo

logger = logging.getLogger("auditforge.importers.unknown_parser")


# ═══════════════════════════════════════════════════════════════════════════════
#  Platform detection via LLM
# ═══════════════════════════════════════════════════════════════════════════════

async def detect_platform_from_content(content: str) -> dict[str, Any]:
    """Use the LLM to detect the target platform from document content.

    Returns a dict with keys:
        platform (str): e.g. "Windows Server 2022"
        platform_family (str): one of linux/windows/network/database/other
        confidence (float): 0.0–1.0
        reasoning (str): brief explanation of detection logic
        benchmark_title (str): best guess at the benchmark/document title
        version (str): detected version string
    """
    # Take a representative sample — first 4000 chars + last 1000 chars
    sample = content[:4000]
    if len(content) > 5000:
        sample += "\n\n[...middle content omitted...]\n\n" + content[-1000:]

    prompt = UNKNOWN_PLATFORM_DETECTION.format(document_sample=sample)

    try:
        result = await llm_manager.invoke_json(
            prompt,
            system_prompt=UNKNOWN_PLATFORM_SYSTEM,
            timeout=120.0,
            task="phase1_parsing",
        )
    except Exception as exc:
        logger.warning("LLM platform detection failed: %s", exc)
        return {
            "platform": "unknown",
            "platform_family": "other",
            "confidence": 0.0,
            "reasoning": f"LLM unavailable: {exc}",
            "benchmark_title": "Unknown Benchmark",
            "version": "unknown",
        }

    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        result = {}

    # Normalise and validate
    platform = str(result.get("platform", "unknown")).strip()
    family = str(result.get("platform_family", "other")).strip().lower()
    if family not in ("linux", "windows", "network", "database", "other"):
        family = "other"

    confidence = 0.0
    try:
        confidence = float(result.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        confidence = 0.0

    return {
        "platform": platform,
        "platform_family": family,
        "confidence": round(confidence, 2),
        "reasoning": str(result.get("reasoning", ""))[:500],
        "benchmark_title": str(result.get("benchmark_title", "Unknown Benchmark")).strip(),
        "version": str(result.get("version", "unknown")).strip(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Rule extraction via LLM
# ═══════════════════════════════════════════════════════════════════════════════

async def extract_rules_from_unknown(
    content: str,
    platform: str,
    platform_family: str,
) -> list[ExtractedRule]:
    """Use the LLM to extract security rules from an unknown document format.

    Processes the document in chunks to handle large files within LLM context
    windows.  Returns a list of ``ExtractedRule`` objects.

    Args:
        content: Full file content.
        platform: Detected or user-confirmed platform string.
        platform_family: One of linux/windows/network/database/other.

    Returns:
        List of ExtractedRule objects extracted by the LLM.
    """
    # Split into chunks that fit within LLM context
    chunks = _split_into_chunks(content, max_chars=3500)
    all_rules: list[ExtractedRule] = []
    seen_sections: set[str] = set()

    for i, chunk in enumerate(chunks):
        logger.info("Processing chunk %d/%d for unknown benchmark", i + 1, len(chunks))
        try:
            chunk_rules = await _extract_from_chunk(
                chunk, platform, platform_family, chunk_index=i, total_chunks=len(chunks),
            )
            # Deduplicate by section_number
            for rule in chunk_rules:
                key = rule.section_number or rule.title
                if key not in seen_sections:
                    seen_sections.add(key)
                    all_rules.append(rule)
        except Exception as exc:
            logger.warning("Failed to extract rules from chunk %d: %s", i + 1, exc)

    logger.info(
        "Unknown benchmark extraction complete: %d rules from %d chunks",
        len(all_rules), len(chunks),
    )
    return all_rules


async def _extract_from_chunk(
    chunk: str,
    platform: str,
    platform_family: str,
    *,
    chunk_index: int = 0,
    total_chunks: int = 1,
) -> list[ExtractedRule]:
    """Extract rules from a single chunk of document text."""
    prompt = UNKNOWN_RULE_EXTRACTION.format(
        document_chunk=chunk,
        platform=platform,
        platform_family=platform_family,
        chunk_number=chunk_index + 1,
        total_chunks=total_chunks,
    )

    result = await llm_manager.invoke_json(
        prompt,
        system_prompt=UNKNOWN_RULE_SYSTEM,
        timeout=300.0,
        task="phase1_parsing",
    )

    # Normalise response
    if isinstance(result, dict):
        for key in ("rules", "data", "results"):
            if key in result and isinstance(result[key], list):
                result = result[key]
                break
        else:
            result = [result] if result else []
    if not isinstance(result, list):
        return []

    rules: list[ExtractedRule] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        rule = _parse_llm_rule(item)
        if rule:
            rules.append(rule)

    return rules


def _parse_llm_rule(item: dict[str, Any]) -> ExtractedRule | None:
    """Convert an LLM-extracted rule dict into an ExtractedRule."""
    section = str(item.get("section_number") or item.get("section") or item.get("id") or "").strip()
    title = str(item.get("title") or item.get("name") or "").strip()

    if not title:
        return None

    # Auto-generate section number if missing
    if not section:
        # Use a hash-based section number for deduplication
        section = f"U-{abs(hash(title)) % 100000:05d}"

    severity = str(item.get("severity", "medium")).strip().lower()
    if severity not in ("critical", "high", "medium", "low", "info"):
        severity = "medium"

    return ExtractedRule(
        section_number=section,
        title=title,
        description=str(item.get("description", "")).strip(),
        severity=severity,
        framework="custom",
        framework_ref=section,
        rationale=str(item.get("rationale", "")).strip(),
        audit_description=str(item.get("audit_description") or item.get("audit", "")).strip(),
        remediation_description=str(item.get("remediation_description") or item.get("remediation", "")).strip(),
        categories=item.get("categories", []) if isinstance(item.get("categories"), list) else [],
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Build PlatformInfo from detection result
# ═══════════════════════════════════════════════════════════════════════════════

def build_platform_info(detection: dict[str, Any]) -> PlatformInfo:
    """Convert LLM platform detection result into a PlatformInfo object."""
    return PlatformInfo(
        source_tool="unknown_import",
        platform=detection.get("platform", "unknown"),
        platform_family=detection.get("platform_family", "other"),
        benchmark_name=detection.get("benchmark_title", "Unknown Benchmark"),
        benchmark_version=detection.get("version", "unknown"),
        scheme="custom",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _split_into_chunks(content: str, max_chars: int = 3500) -> list[str]:
    """Split content into chunks, preferring natural section boundaries.

    Tries to split on double-newlines (paragraph boundaries) first,
    then falls back to single newlines, then hard splits.
    """
    if len(content) <= max_chars:
        return [content]

    chunks: list[str] = []
    remaining = content

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        # Try to find a good break point
        candidate = remaining[:max_chars]

        # Prefer double-newline break
        break_pos = candidate.rfind("\n\n")
        if break_pos < max_chars * 0.3:
            # Too early — try single newline
            break_pos = candidate.rfind("\n")
        if break_pos < max_chars * 0.3:
            # Last resort — hard split
            break_pos = max_chars

        chunks.append(remaining[:break_pos].strip())
        remaining = remaining[break_pos:].strip()

    return [c for c in chunks if c]  # Filter empty
