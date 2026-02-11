"""Scan executor — orchestrates network scan execution.

Responsible for:
1. Connecting to the target via the appropriate connector
2. Running selected rules' audit commands
3. Evaluating results against expected output regex
4. Storing findings in the database
5. Tracking progress for live UI updates
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.config import settings
from backend.connectors import get_connector
from backend.connectors.base import BaseConnector, CommandResult
from backend.core.exceptions import ConnectionFailedError, ScanCancelledError
from backend.models.finding import Finding
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.scan import Scan
from backend.models.target import Target
from backend.utils.encryption import decrypt_value

logger = logging.getLogger("auditforge.scan_executor")

# Statuses that should be skipped during scanning
_SKIP_STATUSES = {"skipped", "manual", "not_applicable"}

# In-memory progress tracking for active scans (scan_id -> progress dict)
_scan_progress: dict[int, dict[str, Any]] = {}
_progress_lock = threading.Lock()

# Set of scan IDs that have been cancelled
_cancelled_scans: set[int] = set()

# Maximum consecutive command execution errors before aborting
MAX_CONSECUTIVE_ERRORS = 20


def get_scan_progress(scan_id: int) -> dict[str, Any] | None:
    """Return current progress for an active scan, or None."""
    with _progress_lock:
        prog = _scan_progress.get(scan_id)
        return dict(prog) if prog else None


def cancel_scan(scan_id: int) -> bool:
    """Mark a scan as cancelled.  Returns True if the scan was active."""
    with _progress_lock:
        if scan_id in _scan_progress:
            _cancelled_scans.add(scan_id)
            return True
    return False


def _decrypt_target_password(target: Target) -> str | None:
    """Decrypt the target's password if present."""
    if target.ssh_password_encrypted:
        try:
            return decrypt_value(target.ssh_password_encrypted, settings.SECRET_KEY)
        except Exception:
            logger.warning("Failed to decrypt password for target %s", target.id)
    return None


def _evaluate_result(
    result: CommandResult,
    expected_regex: str | None,
) -> str:
    """Evaluate a command result and return a compliance status.

    Returns one of: PASS, FAIL, ERROR
    """
    # Error case — non-zero exit code and no useful output
    if result.exit_code != 0 and not result.stdout.strip():
        return "ERROR"

    # No regex to check against — just check the command didn't error
    if not expected_regex:
        if result.exit_code == 0:
            return "PASS"
        return "FAIL"

    # Check output against expected pattern
    try:
        if re.search(expected_regex, result.stdout, re.MULTILINE | re.IGNORECASE):
            return "PASS"
    except re.error:
        logger.warning("Invalid regex pattern: %s", expected_regex)
        # If regex is invalid, fall through to FAIL

    return "FAIL"


async def execute_network_scan(
    db_factory,
    scan_id: int,
    target_id: int,
    benchmark_id: int,
    selected_rule_ids: list[int] | None = None,
    category_filter: list[str] | None = None,
    severity_filter: list[str] | None = None,
    profile_filter: str | None = None,
    preset_id: int | None = None,
) -> None:
    """Run a full network scan asynchronously.

    This is the main entry point called from the API layer as a background task.
    It uses ``db_factory`` (a callable returning a new DB session) rather than
    accepting a session directly, because the scan runs in a background task.
    """
    db: Session = db_factory()
    connector: BaseConnector | None = None

    try:
        # 1. Load scan, target, and rules
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        target = db.query(Target).filter(Target.id == target_id).first()

        if not scan or not target:
            logger.error("Scan %s or target %s not found", scan_id, target_id)
            return

        # 2. Update scan to running
        scan.status = "running"
        scan.started_at = datetime.now(timezone.utc)
        db.commit()

        # 3. Decrypt credentials and attach to target
        target._decrypted_password = _decrypt_target_password(target)

        # 4. Get the right connector
        try:
            connector = get_connector(
                target.target_type, target.connection_method
            )
        except ValueError as exc:
            scan.status = "failed"
            scan.notes = str(exc)
            db.commit()
            return

        # 5. Connect
        try:
            await connector.connect(target)
        except (ConnectionError, ImportError) as exc:
            scan.status = "failed"
            scan.notes = f"Connection failed: {exc}"
            db.commit()
            return

        # 6. Gather system info
        try:
            sys_info = await connector.get_system_info()
            target.os_details = json.dumps(sys_info)
            db.commit()
        except Exception as exc:
            logger.warning("Failed to collect system info: %s", exc)

        # 7. Build the list of rules to scan
        rules_query = (
            db.query(Rule)
            .filter(Rule.benchmark_id == benchmark_id, Rule.enabled.is_(True))
        )
        if selected_rule_ids:
            rules_query = rules_query.filter(Rule.id.in_(selected_rule_ids))
        if severity_filter:
            rules_query = rules_query.filter(Rule.severity.in_(severity_filter))
        if profile_filter:
            rules_query = rules_query.filter(
                Rule.profile_applicability.contains(profile_filter)
            )

        rules = rules_query.order_by(Rule.section_number).all()

        # If category filter, filter by tags
        if category_filter:
            filtered_rules = []
            for rule in rules:
                rule_tags = [t.tag_id for t in rule.tags] if rule.tags else []
                if any(cat in rule_tags for cat in category_filter):
                    filtered_rules.append(rule)
            rules = filtered_rules

        total = len(rules)

        # 8. Initialise progress tracker
        with _progress_lock:
            _scan_progress[scan_id] = {
                "scan_id": scan_id,
                "status": "running",
                "progress": 0,
                "total": total,
                "current_rule": "",
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "compliance_percentage": 0.0,
            }

        passed = failed = errors = 0
        consecutive_errors = 0

        # 9. Execute each rule
        for idx, rule in enumerate(rules):
            # Check for cancellation
            if scan_id in _cancelled_scans:
                scan.status = "cancelled"
                scan.notes = f"Cancelled after {idx} of {total} rules"
                break

            # Get the command for this rule
            cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule.id).first()
            if not cmd or not cmd.audit_command:
                continue
            if cmd.status in _SKIP_STATUSES:
                continue

            # Update progress
            with _progress_lock:
                _scan_progress[scan_id]["progress"] = idx + 1
                _scan_progress[scan_id]["current_rule"] = rule.section_number

            # Execute
            try:
                result = await connector.execute(cmd.audit_command, timeout=30)
                if result.exit_code == 0 or result.stdout.strip():
                    consecutive_errors = 0  # Reset on success
            except Exception as exc:
                result = CommandResult(
                    stdout="", stderr=str(exc), exit_code=-1, execution_time_ms=0
                )
                consecutive_errors += 1

            # Evaluate
            status = _evaluate_result(result, cmd.expected_output_regex)
            if status == "PASS":
                passed += 1
                consecutive_errors = 0
            elif status == "FAIL":
                failed += 1
            else:
                errors += 1

            # Store finding
            finding = Finding(
                scan_id=scan_id,
                rule_id=rule.id,
                status=status,
                actual_output=result.stdout[:4000] if result.stdout else result.stderr[:4000],
                expected_output=cmd.expected_output_regex,
                severity=rule.severity,
            )
            db.add(finding)
            db.commit()

            # Update running progress
            checked = passed + failed + errors
            pct = (passed / checked * 100) if checked > 0 else 0.0
            with _progress_lock:
                _scan_progress[scan_id].update(
                    {
                        "passed": passed,
                        "failed": failed,
                        "errors": errors,
                        "compliance_percentage": round(pct, 1),
                    }
                )

            # Abort if too many consecutive errors (likely connection issue)
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                scan.status = "failed"
                scan.notes = (
                    f"Aborted after {consecutive_errors} consecutive errors "
                    f"at rule {idx + 1}/{total}. Possible connection issue."
                )
                logger.error(
                    "Scan %s aborted: %d consecutive errors",
                    scan_id, consecutive_errors,
                )
                break

        # 10. Finalize scan
        if scan.status not in ("cancelled", "failed"):
            scan.status = "completed"
        scan.completed_at = datetime.now(timezone.utc)
        scan.total_rules = total
        scan.total_rules_checked = passed + failed + errors
        scan.passed = passed
        scan.failed = failed
        scan.errors = errors
        total_checked = passed + failed + errors
        scan.compliance_percentage = (
            round(passed / total_checked * 100, 1) if total_checked > 0 else 0.0
        )
        db.commit()

        logger.info(
            "Scan %s completed: %s/%s passed (%.1f%%)",
            scan_id,
            passed,
            total_checked,
            scan.compliance_percentage,
        )

    except Exception as exc:
        logger.error("Scan %s failed with unexpected error: %s", scan_id, exc)
        try:
            scan = db.query(Scan).filter(Scan.id == scan_id).first()
            if scan:
                scan.status = "failed"
                scan.notes = f"Unexpected error: {exc}"
                scan.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass

    finally:
        # Clean up
        try:
            if connector:
                try:
                    await connector.disconnect()
                except Exception:
                    pass
        finally:
            with _progress_lock:
                _scan_progress.pop(scan_id, None)
                _cancelled_scans.discard(scan_id)
            db.close()
