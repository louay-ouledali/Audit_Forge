"""Phase 3: Optional LLM-powered validation & correction of generated audit commands."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.ai.benchmark_ai import validate_commands_batch
from backend.core.exceptions import LLMTimeoutError, LLMUnavailableError
from backend.database import SessionLocal
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand

logger = logging.getLogger("auditforge.phase3")

# In-memory tracking of pause requests (benchmark_id -> bool)
_pause_requests: dict[int, bool] = {}

# Rules per LLM call — validation context is lighter than generation
SUB_BATCH_SIZE = 5
# How many LLM calls run concurrently
CONCURRENCY = 3
# Rules fetched per processing cycle (split into concurrent sub-batches)
CYCLE_SIZE = SUB_BATCH_SIZE * CONCURRENCY  # 15

MAX_CONSECUTIVE_FAILURES = 5


def request_pause(benchmark_id: int) -> None:
    """Request Phase 3 to pause for a benchmark."""
    _pause_requests[benchmark_id] = True


def clear_pause(benchmark_id: int) -> None:
    """Clear pause request for a benchmark."""
    _pause_requests.pop(benchmark_id, None)


def is_paused(benchmark_id: int) -> bool:
    """Check if Phase 3 is paused for a benchmark."""
    return _pause_requests.get(benchmark_id, False)


async def run_phase3(benchmark_id: int) -> None:
    """Execute Phase 3 validation with concurrent LLM calls."""
    db = SessionLocal()
    try:
        benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
        if not benchmark:
            logger.error("Benchmark %d not found", benchmark_id)
            return

        benchmark.phase3_status = "processing"
        clear_pause(benchmark_id)
        db.commit()

        platform = benchmark.platform
        platform_family = benchmark.platform_family

        # Get all rules with generated commands (not failed, not protected)
        rules_with_commands: list[tuple[Rule, RuleCommand]] = (
            db.query(Rule, RuleCommand)
            .join(RuleCommand, Rule.id == RuleCommand.rule_id)
            .filter(
                Rule.benchmark_id == benchmark_id,
                RuleCommand.status.in_(["generated", "verified"]),
                # Skip commands already processed by a previous Phase 3 run
                ~RuleCommand.validation_status.in_(["applied", "dismissed", "validated", "corrected", "flagged"]),
                RuleCommand.audit_command.isnot(None),
                RuleCommand.audit_command != "",
            )
            .order_by(Rule.section_number)
            .all()
        )

        total_to_process = len(rules_with_commands)
        processed = 0
        validated_count = 0
        corrected_count = 0
        flagged_count = 0
        consecutive_failures = 0

        logger.info(
            "Phase 3: %d rules to validate for benchmark %d (concurrency=%d, sub_batch=%d)",
            total_to_process, benchmark_id, CONCURRENCY, SUB_BATCH_SIZE,
        )

        if total_to_process == 0:
            benchmark.phase3_status = "completed"
            benchmark.phase3_stats = json.dumps({
                "total": 0, "processed": 0,
                "validated": 0, "corrected": 0, "flagged": 0,
            })
            db.commit()
            return

        semaphore = asyncio.Semaphore(CONCURRENCY)

        # Process in cycles of CYCLE_SIZE, each cycle fans out into concurrent sub-batches
        for cycle_start in range(0, total_to_process, CYCLE_SIZE):
            # Check for pause
            if is_paused(benchmark_id):
                logger.info(
                    "Phase 3 paused for benchmark %d at %d/%d",
                    benchmark_id, processed, total_to_process,
                )
                benchmark.phase3_status = "paused"
                _update_stats(benchmark, total_to_process, processed,
                              validated_count, corrected_count, flagged_count)
                db.commit()
                return

            cycle = rules_with_commands[cycle_start : cycle_start + CYCLE_SIZE]

            # Split cycle into sub-batches for concurrent LLM calls
            sub_batches: list[list[tuple[Rule, RuleCommand]]] = []
            for i in range(0, len(cycle), SUB_BATCH_SIZE):
                sub_batches.append(cycle[i : i + SUB_BATCH_SIZE])

            async def _process_sub_batch(
                sb: list[tuple[Rule, RuleCommand]],
            ) -> list[tuple[tuple[Rule, RuleCommand], dict[str, Any] | None]]:
                async with semaphore:
                    rules_for_llm: list[dict[str, Any]] = []
                    for rule, cmd in sb:
                        rules_for_llm.append({
                            "section_number": rule.section_number,
                            "title": rule.title,
                            "audit_description_raw": rule.audit_description_raw or "",
                            "audit_command": cmd.audit_command or "",
                            "expected_output_regex": cmd.expected_output_regex or "",
                            "expected_output_description": cmd.expected_output_description or "",
                        })

                    try:
                        results = await validate_commands_batch(
                            rules_for_llm, platform, platform_family,
                        )
                    except (LLMTimeoutError, LLMUnavailableError, Exception) as exc:
                        sections = [r.section_number for r, _ in sb]
                        logger.warning("Phase 3 sub-batch [%s] failed: %s", ",".join(sections), exc)
                        return [(pair, None) for pair in sb]

                    # Match results by section_number or position
                    by_sec: dict[str, dict[str, Any]] = {}
                    for item in results:
                        sec = item.get("section_number", "")
                        if sec:
                            by_sec[sec] = item

                    matched: list[tuple[tuple[Rule, RuleCommand], dict[str, Any] | None]] = []
                    for pos, pair in enumerate(sb):
                        rule, cmd = pair
                        sec = rule.section_number or ""
                        validation = by_sec.get(sec)
                        if not validation and pos < len(results):
                            validation = results[pos]
                        matched.append((pair, validation))
                    return matched

            # Fire all sub-batches concurrently
            tasks = [_process_sub_batch(sb) for sb in sub_batches]
            sub_results = await asyncio.gather(*tasks)

            # Collect results
            now = datetime.now(timezone.utc)
            cycle_had_success = False

            for batch_result in sub_results:
                for (rule, cmd), validation in batch_result:
                    if not validation:
                        continue

                    cycle_had_success = True
                    status = validation.get("status", "validated")
                    confidence = validation.get("confidence", "medium")
                    corrections = validation.get("corrections", [])
                    notes = validation.get("notes", "")

                    cmd.validation_status = status
                    cmd.validation_confidence = confidence
                    cmd.validation_corrections = json.dumps(corrections) if corrections else None
                    cmd.validation_notes = notes
                    cmd.validated_at = now

                    if status == "validated":
                        validated_count += 1
                    elif status == "corrected":
                        corrected_count += 1
                    elif status == "flagged":
                        flagged_count += 1

            if cycle_had_success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    benchmark.phase3_status = "failed"
                    _update_stats(benchmark, total_to_process, processed,
                                  validated_count, corrected_count, flagged_count)
                    benchmark.notes = f"Phase 3 stopped: {consecutive_failures} consecutive cycle failures"
                    db.commit()
                    return

            processed += len(cycle)
            _update_stats(benchmark, total_to_process, processed,
                          validated_count, corrected_count, flagged_count)
            db.commit()
            logger.info(
                "Phase 3: %d/%d validated for benchmark %d",
                processed, total_to_process, benchmark_id,
            )

        # All done
        benchmark.phase3_status = "completed"
        _update_stats(benchmark, total_to_process, processed,
                      validated_count, corrected_count, flagged_count)
        db.commit()
        logger.info("Phase 3 completed for benchmark %d", benchmark_id)

    except Exception as exc:
        logger.error("Phase 3 failed for benchmark %d: %s", benchmark_id, exc, exc_info=True)
        db.rollback()
        try:
            benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
            if benchmark:
                benchmark.phase3_status = "failed"
                benchmark.notes = f"Phase 3 error: {exc}"
                db.commit()
        except Exception:
            pass
    finally:
        clear_pause(benchmark_id)
        db.close()


def _update_stats(
    benchmark: Benchmark,
    total: int,
    processed: int,
    validated: int,
    corrected: int,
    flagged: int,
) -> None:
    """Update Phase 3 stats on the benchmark model."""
    benchmark.phase3_stats = json.dumps({
        "total": total,
        "processed": processed,
        "validated": validated,
        "corrected": corrected,
        "flagged": flagged,
    })


def apply_corrections(db: Session, rule_command_id: int) -> RuleCommand:
    """Apply LLM-suggested corrections to a rule command.

    Only applies corrections for fields: audit_command, expected_output_regex,
    expected_output_description, remediation_command.
    """
    cmd = db.query(RuleCommand).filter(RuleCommand.id == rule_command_id).first()
    if not cmd:
        raise ValueError(f"RuleCommand {rule_command_id} not found")

    if not cmd.validation_corrections:
        raise ValueError("No corrections to apply")

    corrections = json.loads(cmd.validation_corrections)
    if not corrections:
        raise ValueError("Corrections list is empty")

    ALLOWED_FIELDS = {"audit_command", "expected_output_regex",
                      "expected_output_description", "remediation_command"}

    now = datetime.now(timezone.utc)
    applied_count = 0

    for corr in corrections:
        field = corr.get("field", "")
        if field not in ALLOWED_FIELDS:
            continue
        new_value = corr.get("new_value", "")
        if new_value:
            setattr(cmd, field, new_value)
            applied_count += 1

    if applied_count > 0:
        cmd.validation_status = "applied"
        cmd.source = "phase3_corrected"
        cmd.updated_at = now
        cmd.validation_corrections = None  # clear so they don't reappear on re-run

    db.commit()
    return cmd


def dismiss_corrections(db: Session, rule_command_id: int) -> RuleCommand:
    """Dismiss LLM corrections for a rule command (keep original)."""
    cmd = db.query(RuleCommand).filter(RuleCommand.id == rule_command_id).first()
    if not cmd:
        raise ValueError(f"RuleCommand {rule_command_id} not found")

    cmd.validation_status = "dismissed"
    cmd.validation_corrections = None  # clear so they don't reappear on re-run
    cmd.updated_at = datetime.now(timezone.utc)
    db.commit()
    return cmd
