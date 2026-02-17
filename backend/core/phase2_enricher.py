"""Phase 2: Generate audit commands for all rules using LLM."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.ai.benchmark_ai import generate_commands_for_batch
from backend.core.exceptions import LLMTimeoutError, LLMUnavailableError
from backend.database import SessionLocal
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand

logger = logging.getLogger("auditforge.phase2")

# In-memory tracking of pause requests (benchmark_id -> bool)
_pause_requests: dict[int, bool] = {}

BATCH_SIZE = 15  # Rules per enrichment cycle (split into concurrent sub-batches)

# Maximum consecutive batch failures before stopping enrichment
MAX_CONSECUTIVE_FAILURES = 10


def request_pause(benchmark_id: int) -> None:
    """Request Phase 2 to pause for a benchmark."""
    _pause_requests[benchmark_id] = True


def clear_pause(benchmark_id: int) -> None:
    """Clear pause request for a benchmark."""
    _pause_requests.pop(benchmark_id, None)


def is_paused(benchmark_id: int) -> bool:
    """Check if Phase 2 is paused for a benchmark."""
    return _pause_requests.get(benchmark_id, False)


async def run_phase2(benchmark_id: int) -> None:
    """Execute Phase 2 enrichment. Generates audit commands for all rules without commands."""
    db = SessionLocal()
    try:
        benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
        if not benchmark:
            logger.error("Benchmark %d not found", benchmark_id)
            return

        benchmark.phase2_status = "processing"
        clear_pause(benchmark_id)
        db.commit()

        platform = benchmark.platform
        platform_family = benchmark.platform_family

        # Delete previously failed RuleCommand rows so they can be retried
        failed_cmds = (
            db.query(RuleCommand)
            .join(Rule)
            .filter(Rule.benchmark_id == benchmark_id, RuleCommand.status == "failed")
            .all()
        )
        for fc in failed_cmds:
            db.delete(fc)
        db.commit()

        # Get rules that don't have commands yet (includes just-deleted failed ones)
        rules_without_commands = (
            db.query(Rule)
            .outerjoin(RuleCommand)
            .filter(Rule.benchmark_id == benchmark_id, RuleCommand.id.is_(None))
            .order_by(Rule.section_number)
            .all()
        )

        total_to_process = len(rules_without_commands)
        processed = 0
        consecutive_failures = 0
        logger.info("Phase 2: %d rules to enrich for benchmark %d", total_to_process, benchmark_id)

        # Handle empty benchmark case
        if total_to_process == 0:
            benchmark.phase2_status = "completed"
            benchmark.enrichment_stats = json.dumps({"total": 0, "processed": 0})
            benchmark.notes = "No rules require enrichment"
            db.commit()
            logger.info("Phase 2: No rules to enrich for benchmark %d", benchmark_id)
            return

        # Process in batches
        for batch_start in range(0, total_to_process, BATCH_SIZE):
            # Check for pause
            if is_paused(benchmark_id):
                logger.info("Phase 2 paused for benchmark %d at rule %d/%d", benchmark_id, processed, total_to_process)
                benchmark.phase2_status = "paused"
                benchmark.enrichment_stats = json.dumps({"total": total_to_process, "processed": processed})
                db.commit()
                return

            batch_rules = rules_without_commands[batch_start : batch_start + BATCH_SIZE]

            # Prepare batch data for LLM
            rules_for_llm = []
            for rule in batch_rules:
                rules_for_llm.append({
                    "section_number": rule.section_number,
                    "title": rule.title,
                    "audit_description_raw": rule.audit_description_raw or "",
                    "remediation_description_raw": rule.remediation_description_raw or "",
                })

            try:
                results = await generate_commands_for_batch(rules_for_llm, platform, platform_family)
            except (LLMTimeoutError, LLMUnavailableError) as exc:
                consecutive_failures += 1
                logger.warning(
                    "LLM failure at batch %d (consecutive: %d/%d): %s",
                    batch_start, consecutive_failures, MAX_CONSECUTIVE_FAILURES, exc,
                )
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        "Phase 2 stopped for benchmark %d: %d consecutive LLM failures",
                        benchmark_id, consecutive_failures,
                    )
                    benchmark.phase2_status = "failed"
                    benchmark.notes = (
                        f"Stopped after {consecutive_failures} consecutive LLM failures. "
                        f"Last error: {exc}"
                    )
                    benchmark.enrichment_stats = json.dumps({"total": total_to_process, "processed": processed})
                    db.commit()
                    return
                # Mark batch as failed and continue
                for rule in batch_rules:
                    if not rule.commands:
                        cmd = RuleCommand(
                            rule_id=rule.id,
                            status="failed",
                            source="llm_generated",
                        )
                        db.add(cmd)
                processed += len(batch_rules)
                db.commit()
                continue
            except Exception as exc:
                consecutive_failures += 1
                logger.warning("Batch starting at %d failed: %s", batch_start, exc)
                # Mark these rules with empty commands so we can retry later
                for rule in batch_rules:
                    if not rule.commands:
                        cmd = RuleCommand(
                            rule_id=rule.id,
                            status="failed",
                            source="llm_generated",
                        )
                        db.add(cmd)
                processed += len(batch_rules)
                db.commit()
                continue

            # Save results
            batch_had_success = False
            for i, rule in enumerate(batch_rules):
                if i < len(results) and results[i].get("audit_command"):
                    result = results[i]
                    now = datetime.now(timezone.utc)
                    cmd = RuleCommand(
                        rule_id=rule.id,
                        audit_command=result.get("audit_command"),
                        expected_output_regex=result.get("expected_output_regex"),
                        expected_output_description=result.get("expected_output_description"),
                        remediation_command=result.get("remediation_command"),
                        remediation_description=result.get("remediation_description"),
                        status="generated",
                        source="llm_generated",
                        created_at=now,
                    )
                    db.add(cmd)
                    batch_had_success = True
                else:
                    # LLM returned empty result for this rule — mark failed
                    cmd = RuleCommand(
                        rule_id=rule.id,
                        status="failed",
                        source="llm_generated",
                    )
                    db.add(cmd)

            if batch_had_success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1

            processed += len(batch_rules)
            benchmark.enrichment_stats = json.dumps({"total": total_to_process, "processed": processed})
            db.commit()
            logger.info("Phase 2: %d/%d rules enriched for benchmark %d", processed, total_to_process, benchmark_id)

        # All done
        benchmark.phase2_status = "completed"
        benchmark.enrichment_stats = json.dumps({"total": total_to_process, "processed": processed})
        db.commit()
        logger.info("Phase 2 completed for benchmark %d", benchmark_id)

    except Exception as exc:
        logger.error("Phase 2 failed for benchmark %d: %s", benchmark_id, exc, exc_info=True)
        db.rollback()
        try:
            benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
            if benchmark:
                benchmark.phase2_status = "failed"
                benchmark.notes = str(exc)
                db.commit()
        except Exception:
            pass
    finally:
        clear_pause(benchmark_id)
        db.close()
