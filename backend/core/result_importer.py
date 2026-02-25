"""Result importer — parses uploaded scan results and creates findings."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.core.comparison_engine import evaluate as evaluate_expression
from backend.core.error_patterns import classify_output
from backend.models.finding import Finding
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.scan import Scan

logger = logging.getLogger("auditforge.result_importer")

# Truncate captured output to avoid storing excessively large blobs.
# 4000 chars is sufficient context for auditor review while keeping the DB lean.
MAX_OUTPUT_LENGTH = 4000


def parse_json_results(raw: str, scan_id: int, benchmark_id: int, db: Session) -> dict[str, Any]:
    """Parse audit_results.json format (Linux/Windows mode B scripts).

    Expected JSON format:
    [
        {
            "rule_id": "5.2.4",       # section_number
            "status": "PASS",          # PASS, FAIL, ERROR
            "actual_output": "..."     # captured stdout
        },
        ...
    ]

    Returns dict with stats: findings_created, passed, failed, errors, compliance_percentage
    """
    try:
        results = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}")

    if not isinstance(results, list):
        raise ValueError("Expected a JSON array of results")

    passed = failed = errors = 0
    findings_created = 0

    for entry in results:
        section = entry.get("rule_id") or entry.get("section_number")
        if not section:
            continue

        rule = (
            db.query(Rule)
            .filter(Rule.benchmark_id == benchmark_id, Rule.section_number == str(section))
            .first()
        )
        if not rule:
            logger.warning("Rule not found for section %s", section)
            continue

        status = (entry.get("status") or "MANUAL_REVIEW").upper()
        if status not in ("PASS", "FAIL", "ERROR", "MANUAL_REVIEW", "NOT_APPLICABLE", "SKIPPED"):
            status = "MANUAL_REVIEW"

        actual = entry.get("actual_output", "")

        cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule.id).first()

        # ── Re-classify using error patterns (mirrors PS template logic) ──
        # Even when the PS script already set a status, double-check the
        # actual_output for execution-error patterns.  The PS template's
        # Test-ExecutionError already catches most, but if any slip through
        # (e.g. older script versions) we correct them here.
        output_category = classify_output(actual)
        if output_category == "execution_error" and status != "ERROR":
            status = "ERROR"
        elif output_category == "not_configured" and status == "FAIL":
            # Already correct (FAIL = Not Configured in CIS), keep explanation
            pass
        elif output_category == "service_not_found" and status == "FAIL":
            # Re-evaluate: if expected is ==Disabled, service not installed → PASS
            if cmd and cmd.expected_output_regex:
                comp_result = evaluate_expression(cmd.expected_output_regex, "Disabled")
                if comp_result.matched:
                    status = "PASS"

        # If status not provided in JSON, try to evaluate using comparison expression
        if not entry.get("status"):
            if cmd and cmd.expected_output_regex:
                comp_result = evaluate_expression(cmd.expected_output_regex, actual)
                status = "PASS" if comp_result.matched else "FAIL"
            else:
                status = "MANUAL_REVIEW"

        finding = Finding(
            scan_id=scan_id,
            rule_id=rule.id,
            status=status,
            actual_output=actual[:MAX_OUTPUT_LENGTH] if actual else "",
            expected_output=cmd.expected_output_regex if cmd else None,
            severity=rule.severity,
        )

        db.add(finding)
        findings_created += 1

        if status == "PASS":
            passed += 1
        elif status == "FAIL":
            failed += 1
        else:
            errors += 1

    db.flush()
    return _build_stats(findings_created, passed, failed, errors)


def parse_marker_results(raw_text: str, scan_id: int, benchmark_id: int, db: Session) -> dict[str, Any]:
    """Parse marker-based output (databases, network devices).

    Format:
    RULE_START|section_number|severity
    <command output>
    RULE_END|section_number

    The backend evaluates PASS/FAIL using expected_output_regex since
    SQL/CLI environments can't do regex matching natively.

    Returns dict with stats.
    """
    passed = failed = errors = 0
    findings_created = 0

    current_section: str | None = None
    current_severity: str | None = None
    current_output: list[str] = []

    for line in raw_text.splitlines():
        if line.startswith("RULE_START|"):
            parts = line.split("|")
            current_section = parts[1] if len(parts) > 1 else None
            current_severity = parts[2] if len(parts) > 2 else None
            current_output = []

        elif line.startswith("RULE_END|"):
            if current_section:
                output_text = "\n".join(current_output).strip()

                rule = (
                    db.query(Rule)
                    .filter(Rule.benchmark_id == benchmark_id, Rule.section_number == current_section)
                    .first()
                )

                if rule:
                    cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule.id).first()
                    expr = cmd.expected_output_regex if cmd else None

                    # Check for error patterns first (mirrors PS template logic)
                    output_cat = classify_output(output_text)
                    if output_cat == "execution_error":
                        status = "ERROR"
                    elif output_cat == "not_configured":
                        # Evaluate with empty string — missing path = Not Configured
                        if expr:
                            comp_result = evaluate_expression(expr, "")
                            status = "PASS" if comp_result.matched else "FAIL"
                        else:
                            status = "FAIL"
                    elif output_cat == "service_not_found":
                        if expr:
                            comp_result = evaluate_expression(expr, "Disabled")
                            status = "PASS" if comp_result.matched else "FAIL"
                        else:
                            status = "FAIL"
                    elif expr:
                        comp_result = evaluate_expression(expr, output_text)
                        status = "PASS" if comp_result.matched else "FAIL"
                    else:
                        status = "MANUAL_REVIEW"

                    finding = Finding(
                        scan_id=scan_id,
                        rule_id=rule.id,
                        status=status,
                        actual_output=output_text[:MAX_OUTPUT_LENGTH],
                        expected_output=expr,
                        severity=current_severity or rule.severity,
                    )
                    db.add(finding)
                    findings_created += 1

                    if status == "PASS":
                        passed += 1
                    elif status == "FAIL":
                        failed += 1
                    else:
                        errors += 1
                else:
                    logger.warning("Rule not found for section %s", current_section)

            current_section = None
            current_output = []

        elif current_section is not None:
            current_output.append(line)

    db.flush()
    return _build_stats(findings_created, passed, failed, errors)


def _build_stats(findings_created: int, passed: int, failed: int, errors: int) -> dict[str, Any]:
    """Build the standard stats dict returned by import functions."""
    total = passed + failed + errors
    compliance_pct = round(passed / total * 100, 1) if total > 0 else 0.0
    return {
        "findings_created": findings_created,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "compliance_percentage": compliance_pct,
    }


def detect_format_and_import(
    content: str,
    scan_id: int,
    benchmark_id: int,
    db: Session,
) -> dict[str, Any]:
    """Auto-detect the result format and import accordingly.

    - If content is valid JSON array → parse_json_results
    - If content contains RULE_START markers → parse_marker_results
    - Otherwise raise ValueError
    """
    stripped = content.strip().lstrip("\ufeff")  # Strip UTF-8 BOM if present

    # Try JSON first
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            return parse_json_results(stripped, scan_id, benchmark_id, db)
        except (ValueError, json.JSONDecodeError):
            pass

    # Try marker-based
    if "RULE_START|" in stripped:
        return parse_marker_results(stripped, scan_id, benchmark_id, db)

    # Try JSON as fallback (might be wrapped)
    try:
        return parse_json_results(stripped, scan_id, benchmark_id, db)
    except (ValueError, json.JSONDecodeError):
        pass

    raise ValueError("Unrecognized result format. Expected JSON array or marker-based (RULE_START/RULE_END) output.")


def finalize_scan_stats(scan: Scan, stats: dict[str, Any], db: Session) -> None:
    """Update scan record with import results and stats."""
    scan.status = "imported"
    scan.results_imported_at = datetime.now(timezone.utc)
    scan.total_rules_checked = stats["passed"] + stats["failed"] + stats["errors"]
    scan.passed = stats["passed"]
    scan.failed = stats["failed"]
    scan.errors = stats["errors"]
    scan.compliance_percentage = stats["compliance_percentage"]
    if not scan.completed_at:
        scan.completed_at = datetime.now(timezone.utc)
    db.commit()
