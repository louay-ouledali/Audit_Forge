"""Self-healing feedback loop for audit commands.

When a command ERRORs during a scan, this module classifies the failure,
attempts automated pattern-based fixes, and optionally falls back to
LLM regeneration.  Successful corrections are persisted so the same
rule never fails the same way twice.

Usage (from scan_executor)::

    from backend.core.self_healing import attempt_self_heal

    healed = await attempt_self_heal(
        rule_command=cmd,
        error_output=result.stderr,
        exit_code=result.exit_code,
        connector=chosen,
        db=db,
    )
    if healed:
        # Re-execute with healed.corrected_command
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Error Classification
# ═══════════════════════════════════════════════════════════════════

def classify_error(stderr: str, exit_code: int) -> str:
    """Classify error output into a category for targeted fixing."""
    stderr_l = (stderr or "").lower()

    if exit_code == -1 or "timeout" in stderr_l or "timed out" in stderr_l:
        return "timeout"

    if any(k in stderr_l for k in ("permission denied", "access denied",
                                    "insufficient privileges", "not authorized")):
        return "permission"

    if any(k in stderr_l for k in ("command not found", "no such file",
                                    "is not recognized", "not found")):
        return "not_found"

    if any(k in stderr_l for k in ("syntax error", "parse error",
                                    "invalid syntax", "unexpected token")):
        return "syntax"

    if any(k in stderr_l for k in ("connection refused", "could not connect",
                                    "no route to host", "network unreachable")):
        return "connection"

    if exit_code != 0 and not stderr_l.strip():
        return "no_output"

    return "unknown"


# ═══════════════════════════════════════════════════════════════════
# Pattern-Based Fixes
# ═══════════════════════════════════════════════════════════════════

_PATTERN_FIXES: list[tuple[str, str, Any]] = [
    # grep with no matches exits 1 — append || true
    (r"grep\s+", "no_output",
     lambda cmd: cmd.rstrip() + " || true" if "|| true" not in cmd else None),

    # File not found → try alternate common paths
    (r"/etc/httpd/", "not_found",
     lambda cmd: cmd.replace("/etc/httpd/", "/etc/apache2/")),

    (r"/etc/apache2/", "not_found",
     lambda cmd: cmd.replace("/etc/apache2/", "/etc/httpd/")),

    # RHEL vs Debian package managers
    (r"\bdnf\b", "not_found",
     lambda cmd: cmd.replace("dnf", "apt")),

    (r"\bapt\b", "not_found",
     lambda cmd: cmd.replace("apt", "dnf")),

    # systemctl service name variations
    (r"systemctl.*postgresql-\d+", "not_found",
     lambda cmd: re.sub(r'postgresql-\d+', 'postgresql', cmd)),

    # Permission denied → prepend sudo if not already
    (r"^(?!sudo\s)", "permission",
     lambda cmd: f"sudo {cmd}" if not cmd.startswith("sudo") else None),
]


def _try_pattern_fix(cmd: str, error_type: str, stderr: str) -> str | None:
    """Try pattern-based fixes and return corrected command or None."""
    for pattern, target_error, fixer in _PATTERN_FIXES:
        if error_type == target_error and re.search(pattern, cmd):
            fixed = fixer(cmd)
            if fixed and fixed != cmd:
                return fixed
    return None


# ═══════════════════════════════════════════════════════════════════
# Main Self-Heal Entry Point
# ═══════════════════════════════════════════════════════════════════

async def attempt_self_heal(
    rule_command: Any,  # RuleCommand ORM object
    error_output: str,
    exit_code: int,
    connector: Any | None = None,
    db: Session | None = None,
    max_retries: int = 1,
) -> dict[str, Any] | None:
    """Attempt to self-heal a failed command.

    Returns a dict with ``corrected_command``, ``corrected_expression``,
    ``correction_source`` if a fix was found, or ``None`` if no fix is
    possible.
    """
    cmd = rule_command.audit_command or ""
    expr = rule_command.expected_output_regex or ""
    error_type = classify_error(error_output, exit_code)

    logger.info(
        "Self-heal attempt for rule_command %s: error_type=%s",
        rule_command.id, error_type,
    )

    # --- 1. Pattern-based fix (instant, no LLM) ---
    fixed_cmd = _try_pattern_fix(cmd, error_type, error_output)
    if fixed_cmd:
        correction = {
            "corrected_command": fixed_cmd,
            "corrected_expression": expr,
            "correction_source": "pattern_fix",
            "correction_notes": f"Pattern fix for {error_type}",
        }
        _persist_correction(rule_command, cmd, expr, error_output,
                            error_type, correction, db)
        return correction

    # --- 2. LLM regeneration (if connector available) ---
    if max_retries > 0 and (rule_command.regeneration_count or 0) < 3:
        try:
            from backend.ai.benchmark_ai import regenerate_command

            rule = rule_command.rule
            regen = await regenerate_command(
                section_number=rule.section_number if rule else "",
                title=rule.title if rule else "",
                platform=getattr(rule, "platform", "") if rule else "",
                platform_family=getattr(rule, "platform_family", "") if rule else "",
                assessment_type=None,
                audit_description_raw=rule.description if rule else None,
                remediation_description_raw=None,
                current_audit_command=cmd,
                current_expected_output_regex=expr,
                flag_reason=f"Self-heal: {error_type}",
                flag_error_output=error_output[:500] if error_output else None,
                command_transport=rule_command.command_transport,
            )

            new_cmd = regen.get("audit_command", "")
            if new_cmd and new_cmd != cmd:
                correction = {
                    "corrected_command": new_cmd,
                    "corrected_expression": regen.get("expected_output_regex", expr),
                    "correction_source": "llm_regen",
                    "correction_notes": f"LLM regeneration for {error_type}",
                }
                _persist_correction(rule_command, cmd, expr, error_output,
                                    error_type, correction, db)
                return correction
        except Exception as exc:
            logger.warning("LLM regeneration failed during self-heal: %s", exc)

    return None


def _persist_correction(
    rule_command: Any,
    original_cmd: str,
    original_expr: str,
    error_output: str,
    error_type: str,
    correction: dict[str, Any],
    db: Session | None,
) -> None:
    """Persist the correction to DB and update the RuleCommand."""
    if db is None:
        return

    try:
        from backend.models.command_correction import CommandCorrection

        corr = CommandCorrection(
            rule_command_id=rule_command.id,
            original_command=original_cmd,
            original_expression=original_expr,
            error_output=(error_output or "")[:2000],
            error_type=error_type,
            corrected_command=correction.get("corrected_command"),
            corrected_expression=correction.get("corrected_expression"),
            correction_source=correction["correction_source"],
            correction_notes=correction.get("correction_notes"),
        )
        db.add(corr)

        # Update the RuleCommand itself
        rule_command.audit_command = correction["corrected_command"]
        if correction.get("corrected_expression"):
            rule_command.expected_output_regex = correction["corrected_expression"]
        # Preserve original command on first heal only
        if not rule_command.original_command:
            rule_command.original_command = original_cmd
        rule_command.confidence_score = 0.55  # Slightly above LLM default
        rule_command.confidence_source = "self_healed"
        rule_command.regeneration_count = (rule_command.regeneration_count or 0) + 1
        rule_command.last_regenerated_at = datetime.now(timezone.utc)
        rule_command.updated_at = datetime.now(timezone.utc)

        db.commit()
        logger.info(
            "Persisted self-heal correction for rule_command %s: source=%s",
            rule_command.id, correction["correction_source"],
        )
    except Exception as exc:
        logger.warning("Failed to persist self-heal correction: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
