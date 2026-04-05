"""Phase 2: Generate audit commands for all rules using LLM."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session  # UNUSED — safe to remove

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

        # Normalize platform_family (UI may send "Unix", backend uses "linux")
        _PF_NORM = {"unix": "linux", "macos": "linux"}
        platform_family = _PF_NORM.get(platform_family.lower(), platform_family.lower()) if platform_family else "linux"

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

        # ── Smart cache acceleration: query cache FIRST ──
        cache_stats = {"auto_imported": 0, "flagged": 0, "skipped": 0}
        try:
            from backend.core.command_cache_manager import (
                lookup_commands_for_benchmark,
                apply_cached_commands,
            )
            matches = lookup_commands_for_benchmark(db, benchmark_id, min_confidence=0.5, cross_framework=True)
            if matches:
                cache_stats = apply_cached_commands(db, matches, auto_import_threshold=0.9, flag_threshold=0.7)
                db.commit()
                logger.info(
                    "Phase 2 cache acceleration for benchmark %d: %d auto-imported, %d flagged, %d skipped",
                    benchmark_id, cache_stats["auto_imported"], cache_stats["flagged"], cache_stats["skipped"],
                )
        except Exception as cache_exc:
            logger.warning("Cache acceleration failed (non-fatal): %s", cache_exc)

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
        template_count = 0
        llm_count = 0
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
            batch_template = 0
            batch_llm = 0
            for i, rule in enumerate(batch_rules):
                if i < len(results) and results[i].get("audit_command"):
                    result = results[i]
                    source = "template" if result.get("_source") == "template" else "llm_generated"
                    if source == "template":
                        batch_template += 1
                    else:
                        batch_llm += 1
                    now = datetime.now(timezone.utc)
                    cmd = RuleCommand(
                        rule_id=rule.id,
                        audit_command=result.get("audit_command"),
                        command_transport=result.get("command_transport"),
                        expected_output_regex=result.get("expected_output_regex"),
                        expected_output_description=result.get("expected_output_description"),
                        remediation_command=result.get("remediation_command"),
                        remediation_description=result.get("remediation_description"),
                        status="generated",
                        source=source,
                        created_at=now,
                        confidence_score=result.get("_confidence_score", 0.50),
                        confidence_source=result.get("_confidence_source", source),
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

            template_count += batch_template
            llm_count += batch_llm
            processed += len(batch_rules)
            benchmark.enrichment_stats = json.dumps({
                "total": total_to_process,
                "processed": processed,
                "template_matched": template_count,
                "llm_generated": llm_count,
            })
            db.commit()
            logger.info(
                "Phase 2: %d/%d rules enriched (templates=%d, llm=%d) for benchmark %d",
                processed, total_to_process, template_count, llm_count, benchmark_id,
            )

            # Yield control so the frontend can poll updated progress
            await asyncio.sleep(0.05)

        # ── AI severity classification ─────────────────────────
        # Piggyback on Phase 2 LLM work: classify rules that still have
        # the default "medium" severity (e.g. imported rules that didn't
        # match any preloaded benchmark rule by section_number).
        try:
            from backend.importers.severity_enricher import _enrich_severity_with_ai
            medium_rules = (
                db.query(Rule)
                .filter(Rule.benchmark_id == benchmark_id, Rule.severity == "medium")
                .all()
            )
            if medium_rules:
                ai_updated = _enrich_severity_with_ai(medium_rules, db)
                logger.info(
                    "Phase 2: AI severity classification updated %d rules for benchmark %d",
                    ai_updated, benchmark_id,
                )
                db.commit()
        except Exception as sev_exc:
            logger.warning("AI severity classification failed (non-fatal): %s", sev_exc)

        # All done
        benchmark.phase2_status = "completed"
        benchmark.enrichment_stats = json.dumps({
            "total": total_to_process,
            "processed": processed,
            "template_matched": template_count,
            "llm_generated": llm_count,
            "cache_auto_imported": cache_stats.get("auto_imported", 0),
            "cache_flagged": cache_stats.get("flagged", 0),
        })
        db.commit()

        # ── Populate command cache from this benchmark ──
        try:
            from backend.core.command_cache_manager import populate_cache_from_benchmark
            pop_stats = populate_cache_from_benchmark(db, benchmark_id)
            db.commit()
            logger.info(
                "Phase 2 cache population for benchmark %d: %d inserted, %d skipped",
                benchmark_id, pop_stats["inserted"], pop_stats["skipped"],
            )
        except Exception as pop_exc:
            logger.warning("Cache population failed (non-fatal): %s", pop_exc)

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
