"""LLM-as-reviewer semantic pass for audit commands.

After commands are generated (by template or LLM), this module sends
a batch of (rule_title, command, expression) tuples to a lightweight
LLM call that checks for:

* Logic inversions (==sa when it should be !=sa)
* Tautological expressions (>=0)
* Command/expression mismatches
* Wrong transport for the command type
* Missing WHERE clauses in SQL

The reviewer does NOT regenerate commands — it only flags issues and
optionally suggests one-line fixes.  This keeps costs low (small
prompt, fast model).

Usage::

    from backend.core.semantic_reviewer import review_commands_batch
    issues = await review_commands_batch(commands, platform)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_REVIEW_SYSTEM_PROMPT = """You are a CIS benchmark command quality reviewer.
You review audit commands and their comparison expressions for logical correctness.

For each command entry, check for:
1. INVERSION: Expression checks the opposite of what the rule title says
   (e.g., "Ensure X is disabled" but expression is ==ON)
2. TAUTOLOGY: Expression is always true (>=0, <=999999, contains: with empty value)
3. MISMATCH: Command output type doesn't match expression type
   (e.g., command returns text but expression is >=1)
4. MISSING_CONDITION: SQL query missing WHERE clause, risk of checking wrong data
5. TRANSPORT_MISMATCH: Shell command on sql transport, or SQL on shell transport

Respond with a JSON array. For each command with an issue, return:
{"index": N, "issue": "INVERSION|TAUTOLOGY|MISMATCH|MISSING_CONDITION|TRANSPORT_MISMATCH",
 "explanation": "brief explanation", "suggested_fix_expr": "corrected expression or null"}

If a command has no issues, do NOT include it. Return [] if everything looks correct.
Only return the JSON array, no other text."""

_REVIEW_USER_TEMPLATE = """Review these {count} audit commands for platform "{platform}":

{entries}

Return a JSON array of issues found (empty array if no issues)."""


async def review_commands_batch(
    commands: list[dict[str, Any]],
    platform: str,
    batch_size: int = 20,
) -> list[dict[str, Any]]:
    """Review a batch of commands for semantic issues.

    Each item in *commands* should have keys:
    ``title``, ``audit_command``, ``expected_output_regex``,
    ``command_transport``.

    Returns a list of issue dicts with ``index``, ``issue``,
    ``explanation``, and optionally ``suggested_fix_expr``.
    """
    from backend.ai.llm_manager import llm_manager

    all_issues: list[dict[str, Any]] = []

    # Process in sub-batches
    for start in range(0, len(commands), batch_size):
        batch = commands[start : start + batch_size]
        entries_text = _format_entries(batch, start)

        prompt = _REVIEW_USER_TEMPLATE.format(
            count=len(batch),
            platform=platform,
            entries=entries_text,
        )

        try:
            response = await llm_manager.call(
                system_prompt=_REVIEW_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=2000,
            )
            raw = response.strip()

            # Extract JSON array
            m = re.search(r'\[.*\]', raw, re.DOTALL)
            if m:
                issues = json.loads(m.group())
                if isinstance(issues, list):
                    all_issues.extend(issues)
        except Exception as exc:
            logger.warning("Semantic review batch failed: %s", exc)

    logger.info("Semantic review: %d issues found in %d commands",
                len(all_issues), len(commands))
    return all_issues


def _format_entries(batch: list[dict[str, Any]], offset: int) -> str:
    """Format command entries for the review prompt."""
    lines = []
    for i, entry in enumerate(batch):
        idx = offset + i
        title = entry.get("title", "")[:80]
        cmd = entry.get("audit_command", "")[:200]
        expr = entry.get("expected_output_regex", "")
        transport = entry.get("command_transport", "")
        lines.append(
            f"[{idx}] title: {title}\n"
            f"    command: {cmd}\n"
            f"    expression: {expr}\n"
            f"    transport: {transport}"
        )
    return "\n\n".join(lines)


async def apply_review_fixes(
    commands: list[Any],  # list of RuleCommand ORM objects
    issues: list[dict[str, Any]],
    db: Any = None,
    auto_fix: bool = False,
) -> int:
    """Apply suggested fixes from semantic review.

    If *auto_fix* is True, directly updates the RuleCommand objects.
    Otherwise, flags them for manual review.

    Returns the number of commands updated/flagged.
    """
    from datetime import datetime, timezone
    updated = 0

    issue_map: dict[int, dict] = {}
    for iss in issues:
        idx = iss.get("index")
        if idx is not None and 0 <= idx < len(commands):
            issue_map[idx] = iss

    for idx, cmd in enumerate(commands):
        if idx not in issue_map:
            continue

        iss = issue_map[idx]
        explanation = iss.get("explanation", "")
        suggested = iss.get("suggested_fix_expr")

        if auto_fix and suggested:
            cmd.expected_output_regex = suggested
            cmd.confidence_score = 0.65
            cmd.confidence_source = "llm_validated"
            cmd.updated_at = datetime.now(timezone.utc)
        else:
            # Flag for manual review
            cmd.flagged_at = datetime.now(timezone.utc)
            cmd.flag_reason = f"Semantic review: {iss.get('issue', 'UNKNOWN')}: {explanation}"
            cmd.confidence_score = max(0.2, (cmd.confidence_score or 0.5) - 0.2)

        updated += 1

    if db and updated:
        try:
            db.commit()
        except Exception as exc:
            logger.warning("Failed to commit semantic review results: %s", exc)
            db.rollback()

    return updated
