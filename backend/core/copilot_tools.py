"""Forge Copilot — tool handlers for search, create, edit, explain, gaps, pipeline, commands, validation."""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.copilot_engine import (
    PendingRule,
    analyze_coverage_gaps,
    explain_rule as _explain_rule,
    mine_existing_rules,
)
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand

logger = logging.getLogger(__name__)


# Search

def search_rules_handler(
    db: Session,
    benchmark_id: int,
    *,
    query: str,
    platform: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search rules by text across the current benchmark (or all benchmarks)."""
    q = db.query(Rule)
    if benchmark_id:
        q = q.filter(Rule.benchmark_id == benchmark_id)
    elif platform:
        bm_ids = [
            b.id for b in db.query(Benchmark.id).filter(
                Benchmark.platform.ilike(f"%{platform}%")
            ).all()
        ]
        q = q.filter(Rule.benchmark_id.in_(bm_ids))

    # Simple text search on title + description — extract meaningful keywords
    stop_words = {
        "find", "search", "show", "me", "look", "for", "the", "a", "an", "is",
        "are", "rules", "rule", "about", "with", "that", "which", "what", "where",
        "how", "do", "does", "have", "has", "my", "this",
        "any", "all", "get", "in", "on", "of", "to", "and", "or",
    }
    # Detect section numbers (e.g., "1.2.3") and search those separately
    section_pattern = re.findall(r"\d+\.\d+(?:\.\d+)*", query)
    words = [w for w in re.findall(r"\w+", query.lower()) if w not in stop_words and len(w) > 1]
    if not words and not section_pattern:
        words = query.lower().split()

    from sqlalchemy import or_
    conditions = []
    for sec in section_pattern:
        conditions.append(Rule.section_number == sec)
        conditions.append(Rule.section_number.ilike(f"{sec}%"))
    for word in words:
        pattern = f"%{word}%"
        conditions.append(Rule.title.ilike(pattern))
        conditions.append(Rule.description.ilike(pattern))
    if conditions:
        q = q.filter(or_(*conditions))
    rules = q.limit(limit).all()
    return [
        {
            "id": r.id,
            "section_number": r.section_number,
            "title": r.title,
            "description": (r.description or "")[:200],
            "severity": r.severity,
            "benchmark_id": r.benchmark_id,
        }
        for r in rules
    ]


# Create (pending review)

def create_rule_handler(
    db: Session,
    benchmark_id: int,
    *,
    section_number: str,
    title: str,
    description: str = "",
    severity: str = "medium",
    audit_command: str | None = None,
    expected_output_regex: str | None = None,
) -> dict[str, Any]:
    """Create a single pending rule."""
    rule = Rule(
        benchmark_id=benchmark_id,
        section_number=section_number,
        title=title,
        description=description,
        severity=severity,
        source="copilot",
        pending_review=True,
        copilot_confidence=0.5,
    )
    db.add(rule)
    db.flush()

    if audit_command:
        cmd = RuleCommand(
            rule_id=rule.id,
            audit_command=audit_command,
            expected_output_regex=expected_output_regex or "",
            status="generated",
            source="copilot",
        )
        db.add(cmd)

    db.commit()
    return {
        "id": rule.id,
        "section_number": rule.section_number,
        "title": rule.title,
        "severity": rule.severity,
        "pending_review": True,
    }


def create_rules_batch_handler(
    db: Session,
    benchmark_id: int,
    *,
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create multiple pending rules at once."""
    created = []
    for r in rules:
        rule = Rule(
            benchmark_id=benchmark_id,
            section_number=r.get("section_number", "0.0.0"),
            title=r.get("title", "Untitled"),
            description=r.get("description", ""),
            severity=r.get("severity", "medium"),
            source="copilot",
            pending_review=True,
            copilot_confidence=r.get("confidence", 0.5),
            copilot_source_benchmark=r.get("source_benchmark"),
        )
        db.add(rule)
        db.flush()

        cmd_data = r.get("command_data")
        if cmd_data and isinstance(cmd_data, dict):
            cmd = RuleCommand(
                rule_id=rule.id,
                audit_command=cmd_data.get("audit_command", ""),
                expected_output_regex=cmd_data.get("expected_output_regex", ""),
                expected_output_description=cmd_data.get("expected_output_description", ""),
                remediation_command=cmd_data.get("remediation_command", ""),
                remediation_description=cmd_data.get("remediation_description", ""),
                status="generated",
                source=r.get("command_source", "copilot"),
            )
            db.add(cmd)

        created.append({
            "id": rule.id,
            "section_number": rule.section_number,
            "title": rule.title,
            "severity": rule.severity,
            "confidence": rule.copilot_confidence,
        })

    db.commit()
    return {"created": len(created), "rules": created}


# Edit

EDITABLE_FIELDS = {"severity", "title", "description", "rationale", "profile_applicability"}


def edit_rule_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_id: int,
    field_name: str,
    new_value: str,
) -> dict[str, Any]:
    """Edit a single rule field — blocks if command is protected/verified."""
    if field_name not in EDITABLE_FIELDS:
        return {"error": f"Field '{field_name}' is not editable via Copilot."}

    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.benchmark_id == benchmark_id).first()
    if not rule:
        return {"error": f"Rule #{rule_id} not found in this benchmark."}

    cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule_id).first()
    if cmd and cmd.is_protected:
        return {"error": f"Rule #{rule_id} has a protected command. Edit it manually."}
    if cmd and cmd.status in ("verified", "inherited"):
        return {"error": f"Rule #{rule_id} has a verified command. Edit it manually if needed."}

    old_value = getattr(rule, field_name, None)
    setattr(rule, field_name, new_value)
    db.commit()
    return {
        "rule_id": rule_id,
        "field": field_name,
        "old_value": str(old_value)[:100] if old_value else None,
        "new_value": new_value[:100],
    }


def edit_rules_batch_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_ids: list[int],
    field_name: str,
    new_value: str,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Mass edit — returns a preview first, then applies if confirmed=True."""
    if field_name not in EDITABLE_FIELDS:
        return {"error": f"Field '{field_name}' is not editable via Copilot."}

    rules = (
        db.query(Rule)
        .filter(Rule.id.in_(rule_ids), Rule.benchmark_id == benchmark_id)
        .all()
    )
    if not rules:
        return {"error": "No matching rules found."}

    # Check for protected rules (single query instead of N+1)
    protected_ids = set(
        row[0] for row in db.query(RuleCommand.rule_id).filter(
            RuleCommand.rule_id.in_([r.id for r in rules]),
            (RuleCommand.is_protected == True) | RuleCommand.status.in_(("verified", "inherited")),
        ).all()
    )

    editable = [r for r in rules if r.id not in protected_ids]

    if not confirmed:
        return {
            "preview": True,
            "total": len(rules),
            "editable": len(editable),
            "protected_skipped": len(protected_ids),
            "field": field_name,
            "new_value": new_value,
            "sample": [
                {
                    "id": r.id,
                    "section_number": r.section_number,
                    "old_value": str(getattr(r, field_name, ""))[:60],
                }
                for r in editable[:5]
            ],
        }

    # Apply
    for rule in editable:
        setattr(rule, field_name, new_value)
    db.commit()
    return {"applied": len(editable), "skipped_protected": len(protected_ids)}


# Explain

async def explain_rule_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_id: int | None = None,
    section_number: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Explain a rule in plain language."""
    rule = None
    if rule_id:
        rule = db.query(Rule).filter(Rule.id == rule_id, Rule.benchmark_id == benchmark_id).first()
    elif section_number:
        rule = db.query(Rule).filter(
            Rule.section_number == section_number,
            Rule.benchmark_id == benchmark_id,
        ).first()

    # Fallback: search by title keywords from query
    if not rule and query:
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        for word in words:
            rule = db.query(Rule).filter(
                Rule.benchmark_id == benchmark_id,
                Rule.title.ilike(f"%{word}%"),
            ).first()
            if rule:
                break

    if not rule:
        return {"error": "Rule not found."}

    explanation = await _explain_rule(rule, db)
    return {
        "rule_id": rule.id,
        "section_number": rule.section_number,
        "title": rule.title,
        "explanation": explanation,
    }


# Coverage Gaps

def suggest_gaps_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Analyze coverage and suggest missing categories."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        return {"error": "Benchmark not found."}

    rules = db.query(Rule).filter(Rule.benchmark_id == benchmark_id).all()
    gaps = analyze_coverage_gaps(benchmark.platform_family, rules)

    from backend.core.copilot_engine import EXPECTED_CATEGORIES
    expected_total = len(EXPECTED_CATEGORIES.get(benchmark.platform_family, []))
    covered = expected_total - len(gaps)

    return {
        "benchmark_id": benchmark_id,
        "platform_family": benchmark.platform_family,
        "total_rules": len(rules),
        "missing_categories": gaps,
        "coverage_percentage": round((covered / max(expected_total, 1)) * 100) if expected_total else 100,
    }


# Find Similar

def find_similar_handler(
    db: Session,
    benchmark_id: int,
    *,
    description: str,
    platform_family: str | None = None,
) -> list[dict[str, Any]]:
    """Find similar rules in other benchmarks."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    pf = platform_family or (benchmark.platform_family if benchmark else "linux")

    mined = mine_existing_rules(
        platform_family=pf,
        description=description,
        db=db,
        exclude_benchmark_id=benchmark_id,
        threshold=0.2,
        max_results=10,
    )
    return [
        {
            "section_number": r.section_number,
            "title": r.title,
            "description": r.description[:200] if r.description else "",
            "severity": r.severity,
            "confidence": r.confidence,
            "source_benchmark": r.source_benchmark,
        }
        for r in mined
    ]


# Get Rule Details

def get_rule_details_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_id: int | None = None,
    section_number: str | None = None,
) -> dict[str, Any]:
    """Get full details of a specific rule including its command."""
    rule = None
    if rule_id:
        rule = db.query(Rule).filter(Rule.id == rule_id, Rule.benchmark_id == benchmark_id).first()
    elif section_number:
        rule = db.query(Rule).filter(
            Rule.section_number == section_number,
            Rule.benchmark_id == benchmark_id,
        ).first()

    if not rule:
        return {"error": "Rule not found."}

    cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule.id).first()
    result: dict[str, Any] = {
        "id": rule.id,
        "section_number": rule.section_number,
        "title": rule.title,
        "description": rule.description or "",
        "severity": rule.severity,
        "source": rule.source,
        "pending_review": rule.pending_review,
    }
    if cmd:
        result["command"] = {
            "audit_command": cmd.audit_command,
            "expected_output_regex": cmd.expected_output_regex,
            "expected_output_description": cmd.expected_output_description,
            "remediation_command": cmd.remediation_command,
            "status": cmd.status,
            "is_protected": cmd.is_protected,
        }
    return result


# Count Rules

def count_rules_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Get rule counts and severity breakdown for current benchmark."""
    total = db.query(Rule).filter(Rule.benchmark_id == benchmark_id).count()
    pending = db.query(Rule).filter(
        Rule.benchmark_id == benchmark_id, Rule.pending_review == True
    ).count()

    severity_counts = {}
    for sev in ["critical", "high", "medium", "low"]:
        severity_counts[sev] = db.query(Rule).filter(
            Rule.benchmark_id == benchmark_id,
            Rule.severity == sev,
        ).count()

    with_commands = db.query(Rule).join(RuleCommand, Rule.id == RuleCommand.rule_id).filter(
        Rule.benchmark_id == benchmark_id
    ).count()

    return {
        "total_rules": total,
        "pending_review": pending,
        "approved": total - pending,
        "with_commands": with_commands,
        "without_commands": total - with_commands,
        "by_severity": severity_counts,
    }


# Generate Commands

async def generate_commands_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_ids: list[int],
) -> dict[str, Any]:
    """Generate audit commands for rules that don't have them."""
    from backend.ai.benchmark_ai import generate_commands_for_batch

    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        return {"error": "Benchmark not found."}

    rules = db.query(Rule).filter(
        Rule.id.in_(rule_ids), Rule.benchmark_id == benchmark_id
    ).all()

    if not rules:
        return {"error": "No matching rules found."}

    # Build rule dicts for the batch generator
    rule_dicts = []
    for r in rules:
        rule_dicts.append({
            "section_number": r.section_number,
            "title": r.title,
            "audit_description_raw": r.description or "",
            "remediation_description_raw": "",
        })

    try:
        results = await generate_commands_for_batch(
            rule_dicts, benchmark.platform, benchmark.platform_family
        )
        generated = 0
        for i, cmd_data in enumerate(results):
            if cmd_data and cmd_data.get("audit_command"):
                rule = rules[i] if i < len(rules) else None
                if rule:
                    existing = db.query(RuleCommand).filter(RuleCommand.rule_id == rule.id).first()
                    if not existing:
                        cmd = RuleCommand(
                            rule_id=rule.id,
                            audit_command=cmd_data.get("audit_command", ""),
                            expected_output_regex=cmd_data.get("expected_output_regex", ""),
                            expected_output_description=cmd_data.get("expected_output_description", ""),
                            remediation_command=cmd_data.get("remediation_command", ""),
                            status="generated",
                            source="copilot",
                        )
                        db.add(cmd)
                        generated += 1
        db.commit()
        return {"generated": generated, "total_requested": len(rules)}
    except Exception as e:
        logger.exception("Command generation failed")
        return {"error": f"Command generation failed: {str(e)}"}


# Tool registry placeholder (populated at bottom of file after all handlers)
COPILOT_TOOLS: dict[str, dict] = {}


# List Rules

def list_rules_handler(
    db: Session,
    benchmark_id: int,
    *,
    severity: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """List rules in the current benchmark with optional filtering."""
    q = db.query(Rule).filter(Rule.benchmark_id == benchmark_id)
    if severity:
        q = q.filter(Rule.severity == severity.lower())
    total = q.count()
    rules = q.order_by(Rule.section_number).offset(offset).limit(limit).all()
    # Pre-fetch which rules have commands (avoid N+1)
    rule_ids = [r.id for r in rules]
    rule_ids_with_cmds = set(
        row[0] for row in db.query(RuleCommand.rule_id)
        .filter(RuleCommand.rule_id.in_(rule_ids)).all()
    ) if rule_ids else set()
    return {
        "total": total,
        "showing": len(rules),
        "offset": offset,
        "rules": [
            {
                "id": r.id,
                "section_number": r.section_number,
                "title": r.title,
                "description": r.description or "",
                "severity": r.severity,
                "pending_review": r.pending_review,
                "has_command": r.id in rule_ids_with_cmds,
            }
            for r in rules
        ],
    }


# Get Benchmark Info

def get_benchmark_info_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Get benchmark metadata and overall stats."""
    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not bm:
        return {"error": "Benchmark not found."}

    total = db.query(Rule).filter(Rule.benchmark_id == benchmark_id).count()
    pending = db.query(Rule).filter(
        Rule.benchmark_id == benchmark_id, Rule.pending_review == True
    ).count()
    with_commands = db.query(Rule).join(RuleCommand, Rule.id == RuleCommand.rule_id).filter(
        Rule.benchmark_id == benchmark_id
    ).count()

    return {
        "id": bm.id,
        "name": bm.name,
        "platform": bm.platform,
        "platform_family": bm.platform_family,
        "source": bm.source,
        "total_rules": total,
        "pending_review": pending,
        "with_commands": with_commands,
        "phase1_status": bm.phase1_status,
        "phase2_status": bm.phase2_status,
        "phase3_status": bm.phase3_status,
        "is_editable": bm.is_editable,
    }


# Import Rules from Another Benchmark

def import_rules_from_benchmark_handler(
    db: Session,
    benchmark_id: int,
    *,
    source_benchmark_id: int | None = None,
    source_benchmark_name: str | None = None,
    severity: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Import rules from another benchmark into the current one (pending approval)."""
    # Find source benchmark
    source_bm = None
    if source_benchmark_id:
        source_bm = db.query(Benchmark).filter(Benchmark.id == source_benchmark_id).first()
    elif source_benchmark_name:
        source_bm = db.query(Benchmark).filter(
            Benchmark.name.ilike(f"%{source_benchmark_name}%")
        ).first()

    if not source_bm:
        # List available benchmarks
        available = db.query(Benchmark).filter(Benchmark.id != benchmark_id).limit(10).all()
        return {
            "error": "Source benchmark not found.",
            "available_benchmarks": [
                {"id": b.id, "name": b.name, "platform": b.platform, "total_rules": b.total_rules}
                for b in available
            ],
        }

    # Get rules from source
    q = db.query(Rule).filter(Rule.benchmark_id == source_bm.id)
    if severity:
        q = q.filter(Rule.severity == severity.lower())
    source_rules = q.limit(limit).all()

    if not source_rules:
        return {"error": f"No rules found in '{source_bm.name}' matching criteria."}

    # Create pending copies
    created = []
    for sr in source_rules:
        # Check for duplicate section numbers
        existing = db.query(Rule).filter(
            Rule.benchmark_id == benchmark_id,
            Rule.section_number == sr.section_number,
        ).first()
        if existing:
            continue

        rule = Rule(
            benchmark_id=benchmark_id,
            section_number=sr.section_number,
            title=sr.title,
            description=sr.description,
            severity=sr.severity,
            source="copilot",
            pending_review=True,
            copilot_confidence=0.9,
            copilot_source_benchmark=source_bm.name,
        )
        db.add(rule)
        db.flush()

        # Copy command if exists
        src_cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == sr.id).first()
        if src_cmd:
            cmd = RuleCommand(
                rule_id=rule.id,
                audit_command=src_cmd.audit_command,
                expected_output_regex=src_cmd.expected_output_regex,
                expected_output_description=src_cmd.expected_output_description,
                remediation_command=src_cmd.remediation_command,
                remediation_description=src_cmd.remediation_description,
                status="generated",
                source="imported",
            )
            db.add(cmd)

        created.append({
            "id": rule.id,
            "section_number": rule.section_number,
            "title": rule.title,
            "severity": rule.severity,
        })

    db.commit()
    return {
        "source_benchmark": source_bm.name,
        "imported": len(created),
        "skipped_duplicates": len(source_rules) - len(created),
        "rules": created[:10],
    }


# Background task helper

def _run_in_background(fn, *args, **kwargs):
    """Launch a sync or async function in a background daemon thread."""
    import asyncio as _aio

    def _wrapper():
        loop = _aio.new_event_loop()
        _aio.set_event_loop(loop)
        try:
            result = fn(*args, **kwargs)
            if _aio.iscoroutine(result):
                loop.run_until_complete(result)
        except Exception:
            logger.exception("Background task failed: %s", fn.__name__)
        finally:
            loop.close()

    t = threading.Thread(target=_wrapper, daemon=True)
    t.start()


# Pipeline Control tools

def get_pipeline_status_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Get pipeline status for all phases + stats."""
    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not bm:
        return {"error": "Benchmark not found."}

    total = db.query(Rule).filter(Rule.benchmark_id == benchmark_id).count()
    with_cmds = db.query(Rule).join(RuleCommand).filter(Rule.benchmark_id == benchmark_id).count()

    enrichment_stats = None
    if bm.enrichment_stats:
        try:
            enrichment_stats = json.loads(bm.enrichment_stats)
        except (json.JSONDecodeError, TypeError):
            pass

    phase3_stats = None
    if bm.phase3_stats:
        try:
            phase3_stats = json.loads(bm.phase3_stats)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "benchmark_id": benchmark_id,
        "name": bm.name,
        "phase1_status": bm.phase1_status,
        "phase2_status": bm.phase2_status,
        "phase3_status": bm.phase3_status,
        "verification_status": bm.verification_status,
        "is_ready": bm.is_ready,
        "total_rules": total,
        "with_commands": with_cmds,
        "enrichment_stats": enrichment_stats,
        "phase3_stats": phase3_stats,
    }


def start_enrichment_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Start Phase 2 enrichment in background."""
    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not bm:
        return {"error": "Benchmark not found."}
    if bm.phase1_status != "completed":
        return {"error": f"Phase 1 must be completed first (current: {bm.phase1_status})."}
    if bm.phase2_status == "processing":
        return {"error": "Phase 2 is already running."}

    from backend.core.phase2_enricher import run_phase2
    _run_in_background(run_phase2, benchmark_id)

    return {
        "status": "started",
        "message": "Phase 2 enrichment started. Ask me for pipeline status to monitor progress.",
    }


def pause_enrichment_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Pause Phase 2 enrichment."""
    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not bm:
        return {"error": "Benchmark not found."}
    if bm.phase2_status != "processing":
        return {"error": f"Phase 2 is not currently running (status: {bm.phase2_status})."}

    from backend.core.phase2_enricher import request_pause
    request_pause(benchmark_id)

    return {"status": "pause_requested", "message": "Pause requested. Phase 2 will stop after the current batch."}


def start_verification_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Start command verification in background."""
    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not bm:
        return {"error": "Benchmark not found."}
    if bm.phase2_status != "completed":
        return {"error": f"Phase 2 must be completed first (current: {bm.phase2_status})."}
    if bm.verification_status == "processing":
        return {"error": "Verification is already running."}

    from backend.core.verification_engine import run_verification
    _run_in_background(run_verification, benchmark_id)

    return {
        "status": "started",
        "message": "Command verification started. Ask me for pipeline status to monitor progress.",
    }


def start_validation_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Start Phase 3 validation in background."""
    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not bm:
        return {"error": "Benchmark not found."}
    if bm.phase2_status != "completed":
        return {"error": f"Phase 2 must be completed first (current: {bm.phase2_status})."}
    if bm.phase3_status == "processing":
        return {"error": "Phase 3 validation is already running."}

    from backend.core.phase3_validator import run_phase3
    _run_in_background(run_phase3, benchmark_id)

    return {
        "status": "started",
        "message": "Phase 3 validation started. Ask me for pipeline status to monitor progress.",
    }


# Command Management tools

def verify_command_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_id: int,
) -> dict[str, Any]:
    """Verify a single command (static checks, no live target needed)."""
    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.benchmark_id == benchmark_id).first()
    if not rule:
        return {"error": f"Rule #{rule_id} not found."}
    cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule_id).first()
    if not cmd:
        return {"error": f"Rule #{rule_id} has no command."}

    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    from backend.core.verification_engine import verify_single_command
    result = verify_single_command(cmd.audit_command, bm.platform_family if bm else "linux")
    return {
        "rule_id": rule_id,
        "section_number": rule.section_number,
        "passed": result.get("passed", False),
        "issues": result.get("issues", []),
    }


COMMAND_EDITABLE_FIELDS = {"audit_command", "expected_output_regex", "expected_output_description", "remediation_command"}


def edit_command_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_id: int,
    field_name: str,
    new_value: str,
) -> dict[str, Any]:
    """Edit a command field for a rule."""
    if field_name not in COMMAND_EDITABLE_FIELDS:
        return {"error": f"Field '{field_name}' is not editable. Allowed: {', '.join(sorted(COMMAND_EDITABLE_FIELDS))}"}

    cmd = db.query(RuleCommand).join(Rule).filter(
        Rule.id == rule_id, Rule.benchmark_id == benchmark_id,
    ).first()
    if not cmd:
        return {"error": f"No command found for rule #{rule_id}."}
    if cmd.is_protected:
        return {"error": f"Command for rule #{rule_id} is protected."}
    if cmd.status in ("verified", "inherited"):
        return {"error": f"Command for rule #{rule_id} has status '{cmd.status}'. Unprotect or flag it first."}

    old_value = getattr(cmd, field_name, None)
    setattr(cmd, field_name, new_value)
    cmd.source = "copilot_edited"
    cmd.status = "pending_review"
    cmd.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "rule_id": rule_id,
        "field": field_name,
        "old_value": str(old_value)[:100] if old_value else None,
        "new_value": new_value[:100],
    }


def flag_command_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_id: int,
    reason: str,
) -> dict[str, Any]:
    """Flag a command with a reason."""
    cmd = db.query(RuleCommand).join(Rule).filter(
        Rule.id == rule_id, Rule.benchmark_id == benchmark_id,
    ).first()
    if not cmd:
        return {"error": f"No command found for rule #{rule_id}."}
    if cmd.is_protected:
        return {"error": f"Command for rule #{rule_id} is protected and cannot be flagged."}

    cmd.status = "flagged"
    cmd.flag_reason = reason
    cmd.flagged_at = datetime.now(timezone.utc)
    db.commit()

    return {"rule_id": rule_id, "status": "flagged", "reason": reason}


async def regenerate_command_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_id: int,
    error_context: str | None = None,
) -> dict[str, Any]:
    """Regenerate a flagged command using LLM."""
    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.benchmark_id == benchmark_id).first()
    if not rule:
        return {"error": f"Rule #{rule_id} not found."}
    cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule_id).first()
    if not cmd:
        return {"error": f"Rule #{rule_id} has no command to regenerate."}
    if cmd.is_protected:
        return {"error": f"Command is protected."}
    if cmd.status != "flagged":
        return {"error": f"Command must be flagged first (current: {cmd.status})."}

    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()

    # Save current command to history
    prev = []
    if cmd.previous_commands:
        try:
            prev = json.loads(cmd.previous_commands)
        except (json.JSONDecodeError, TypeError):
            pass
    prev.append({
        "audit_command": cmd.audit_command,
        "expected_output_regex": cmd.expected_output_regex,
        "flag_reason": cmd.flag_reason,
        "regenerated_at": datetime.now(timezone.utc).isoformat(),
    })
    cmd.previous_commands = json.dumps(prev)

    from backend.ai.benchmark_ai import regenerate_command
    result = await regenerate_command(
        section_number=rule.section_number,
        title=rule.title,
        platform=bm.platform if bm else "",
        platform_family=bm.platform_family if bm else "linux",
        assessment_type=rule.assessment_type,
        audit_description_raw=rule.audit_description_raw,
        remediation_description_raw=rule.remediation_description_raw,
        current_audit_command=cmd.audit_command,
        current_expected_output_regex=cmd.expected_output_regex,
        flag_reason=cmd.flag_reason or error_context or "Command verification failed",
        flag_error_output=cmd.flag_error_output,
        previous_commands=prev,
    )

    if result and result.get("audit_command"):
        cmd.audit_command = result["audit_command"]
        cmd.expected_output_regex = result.get("expected_output_regex", cmd.expected_output_regex)
        cmd.expected_output_description = result.get("expected_output_description", cmd.expected_output_description)
        cmd.remediation_command = result.get("remediation_command", cmd.remediation_command)
        cmd.status = "generated"
        cmd.source = "copilot_regenerated"
        cmd.flag_reason = None
        cmd.flagged_at = None
        cmd.regeneration_count = (cmd.regeneration_count or 0) + 1
        cmd.last_regenerated_at = datetime.now(timezone.utc)
        db.commit()
        return {"rule_id": rule_id, "status": "regenerated", "new_command": result["audit_command"][:200]}

    return {"error": "Regeneration failed — LLM did not return a valid command."}


def get_command_history_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_id: int,
) -> dict[str, Any]:
    """Get the history of previous commands for a rule."""
    cmd = db.query(RuleCommand).join(Rule).filter(
        Rule.id == rule_id, Rule.benchmark_id == benchmark_id,
    ).first()
    if not cmd:
        return {"error": f"No command found for rule #{rule_id}."}

    history = []
    if cmd.previous_commands:
        try:
            history = json.loads(cmd.previous_commands)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "rule_id": rule_id,
        "current": {
            "audit_command": cmd.audit_command,
            "status": cmd.status,
            "source": cmd.source,
            "regeneration_count": cmd.regeneration_count or 0,
        },
        "history": history,
    }


# Validation Review tools

def get_validation_results_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Get Phase 3 validation corrections for the benchmark."""
    results = (
        db.query(RuleCommand, Rule)
        .join(Rule, RuleCommand.rule_id == Rule.id)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.validation_status.isnot(None),
        )
        .all()
    )

    corrections = []
    for cmd, rule in results:
        parsed_corrections = []
        if cmd.validation_corrections:
            try:
                parsed_corrections = json.loads(cmd.validation_corrections)
            except (json.JSONDecodeError, TypeError):
                pass
        corrections.append({
            "rule_command_id": cmd.id,
            "rule_id": rule.id,
            "section_number": rule.section_number,
            "title": rule.title,
            "validation_status": cmd.validation_status,
            "validation_confidence": cmd.validation_confidence,
            "corrections": parsed_corrections,
            "notes": cmd.validation_notes,
        })

    return {
        "total": len(corrections),
        "corrections": corrections,
        "by_status": {
            s: sum(1 for c in corrections if c["validation_status"] == s)
            for s in {"validated", "corrected", "flagged", "applied", "dismissed"}
        },
    }


def apply_correction_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_command_id: int,
) -> dict[str, Any]:
    """Apply Phase 3 LLM corrections to a command."""
    from backend.core.phase3_validator import apply_corrections as _apply
    try:
        cmd = _apply(db, rule_command_id)
        return {"rule_command_id": cmd.id, "status": "applied"}
    except Exception as e:
        return {"error": str(e)}


def dismiss_correction_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_command_id: int,
) -> dict[str, Any]:
    """Dismiss Phase 3 corrections without applying."""
    from backend.core.phase3_validator import dismiss_corrections as _dismiss
    try:
        cmd = _dismiss(db, rule_command_id)
        return {"rule_command_id": cmd.id, "status": "dismissed"}
    except Exception as e:
        return {"error": str(e)}


def bulk_apply_corrections_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Apply all high-confidence corrections."""
    from backend.core.phase3_validator import apply_corrections as _apply

    cmds = (
        db.query(RuleCommand)
        .join(Rule, RuleCommand.rule_id == Rule.id)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.validation_status == "corrected",
            RuleCommand.validation_confidence == "high",
        )
        .all()
    )

    applied = 0
    errors = 0
    for cmd in cmds:
        try:
            _apply(db, cmd.id)
            applied += 1
        except Exception:
            errors += 1

    return {"applied": applied, "errors": errors, "total_eligible": len(cmds)}


# Intelligence tools

def diff_benchmarks_handler(
    db: Session,
    benchmark_id: int,
    *,
    other_benchmark_id: int,
) -> dict[str, Any]:
    """Diff current benchmark against another to find added/removed/modified rules."""
    base_bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    other_bm = db.query(Benchmark).filter(Benchmark.id == other_benchmark_id).first()
    if not base_bm or not other_bm:
        return {"error": "One or both benchmarks not found."}

    base_rules = {r.section_number: r for r in db.query(Rule).filter(Rule.benchmark_id == benchmark_id).all()}
    other_rules = {r.section_number: r for r in db.query(Rule).filter(Rule.benchmark_id == other_benchmark_id).all()}

    added = []
    removed = []
    modified = []

    for sec, rule in other_rules.items():
        if sec not in base_rules:
            added.append({"section_number": sec, "title": rule.title, "severity": rule.severity})
        else:
            base_rule = base_rules[sec]
            changes = {}
            for field in ("title", "description", "severity"):
                bv = getattr(base_rule, field, "") or ""
                ov = getattr(rule, field, "") or ""
                if bv != ov:
                    changes[field] = {"base": str(bv)[:100], "compare": str(ov)[:100]}
            if changes:
                modified.append({"section_number": sec, "title": rule.title, "changed_fields": changes})

    for sec in base_rules:
        if sec not in other_rules:
            removed.append({"section_number": sec, "title": base_rules[sec].title, "severity": base_rules[sec].severity})

    return {
        "base": {"id": base_bm.id, "name": base_bm.name},
        "compare": {"id": other_bm.id, "name": other_bm.name},
        "added": len(added),
        "removed": len(removed),
        "modified": len(modified),
        "unchanged": len(set(base_rules) & set(other_rules)) - len(modified),
        "details": {
            "added": added[:20],
            "removed": removed[:20],
            "modified": modified[:20],
        },
    }


def get_migration_readiness_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Check if the benchmark is ready for deployment."""
    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not bm:
        return {"error": "Benchmark not found."}

    total = db.query(Rule).filter(Rule.benchmark_id == benchmark_id).count()
    with_cmds = db.query(Rule).join(RuleCommand).filter(Rule.benchmark_id == benchmark_id).count()
    verified = db.query(Rule).join(RuleCommand).filter(
        Rule.benchmark_id == benchmark_id, RuleCommand.status == "verified",
    ).count()
    protected = db.query(Rule).join(RuleCommand).filter(
        Rule.benchmark_id == benchmark_id, RuleCommand.is_protected == True,
    ).count()
    flagged = db.query(Rule).join(RuleCommand).filter(
        Rule.benchmark_id == benchmark_id, RuleCommand.status == "flagged",
    ).count()
    pending = db.query(Rule).filter(
        Rule.benchmark_id == benchmark_id, Rule.pending_review == True,
    ).count()

    readiness = round((verified / max(total, 1)) * 100) if total else 0
    status = "ready" if readiness >= 80 and flagged == 0 and pending == 0 else (
        "partial" if readiness >= 40 else "not_ready"
    )

    return {
        "benchmark_id": benchmark_id,
        "total_rules": total,
        "with_commands": with_cmds,
        "verified": verified,
        "protected": protected,
        "flagged": flagged,
        "pending_review": pending,
        "readiness_percentage": readiness,
        "status": status,
        "recommendations": _readiness_recommendations(bm, total, with_cmds, verified, flagged, pending),
    }


def _readiness_recommendations(bm, total, with_cmds, verified, flagged, pending):
    """Generate actionable recommendations."""
    recs = []
    if pending > 0:
        recs.append(f"Review and approve {pending} pending rule(s).")
    if total > with_cmds:
        recs.append(f"Run Phase 2 enrichment to generate commands for {total - with_cmds} rule(s) without commands.")
    if flagged > 0:
        recs.append(f"Resolve {flagged} flagged command(s) — regenerate or edit them.")
    if with_cmds > verified:
        recs.append(f"Run verification to validate {with_cmds - verified} unverified command(s).")
    if bm.phase3_status not in ("completed",):
        recs.append("Run Phase 3 validation for LLM quality review of commands.")
    if not recs:
        recs.append("Benchmark looks ready for deployment!")
    return recs


def explain_phase2_behavior_handler(
    db: Session,
    benchmark_id: int,
) -> dict[str, Any]:
    """Explain how Phase 2 handles existing commands (zero-DB, zero-LLM tool)."""
    return {
        "explanation": (
            "Phase 2 enrichment only generates commands for rules that have NO RuleCommand record. "
            "Commands created by Copilot (status='generated') are preserved and never overwritten. "
            "Phase 2 only deletes commands with status='failed' before retrying them. "
            "If you create commands via Copilot, those rules will be skipped during Phase 2. "
            "Your copilot-generated commands are safe."
        ),
    }


# Safe Delete tool

def delete_rule_handler(
    db: Session,
    benchmark_id: int,
    *,
    rule_id: int,
) -> dict[str, Any]:
    """Safely delete a rule (only copilot-created or pending rules without protected commands)."""
    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.benchmark_id == benchmark_id).first()
    if not rule:
        return {"error": f"Rule #{rule_id} not found."}

    # Safety checks
    if rule.source not in ("copilot", None) and not rule.pending_review:
        return {"error": f"Cannot delete rule #{rule_id}: it was imported from '{rule.source}'. Only copilot-created or pending rules can be deleted."}

    cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule_id).first()
    if cmd and cmd.is_protected:
        return {"error": f"Cannot delete rule #{rule_id}: its command is protected."}
    if cmd and cmd.status in ("verified", "inherited"):
        return {"error": f"Cannot delete rule #{rule_id}: its command has been {cmd.status}."}

    section = rule.section_number
    title = rule.title
    db.delete(rule)
    db.commit()

    return {"deleted": True, "rule_id": rule_id, "section_number": section, "title": title}


# Inspect Commands (batch — no IDs needed)

def inspect_commands_handler(
    db: Session,
    benchmark_id: int,
    *,
    severity: str | None = None,
    has_command: bool | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Inspect rules with their commands — no individual IDs needed.

    Returns a batch of rules with full command details, useful for
    reviewing command quality without knowing specific rule IDs.
    """
    query = db.query(Rule).filter(Rule.benchmark_id == benchmark_id)
    if severity:
        query = query.filter(Rule.severity == severity)
    rules = query.order_by(Rule.section_number).all()

    # Pre-fetch all commands in one query
    rule_ids = [r.id for r in rules]
    cmds_map: dict[int, RuleCommand] = {}
    if rule_ids:
        cmds = db.query(RuleCommand).filter(RuleCommand.rule_id.in_(rule_ids)).all()
        cmds_map = {c.rule_id: c for c in cmds}

    # Filter by has_command if requested
    if has_command is True:
        rules = [r for r in rules if r.id in cmds_map]
    elif has_command is False:
        rules = [r for r in rules if r.id not in cmds_map]

    results = []
    for r in rules[:limit]:
        entry: dict[str, Any] = {
            "id": r.id,
            "section_number": r.section_number,
            "title": r.title,
            "severity": r.severity,
        }
        cmd = cmds_map.get(r.id)
        if cmd:
            entry["command"] = {
                "audit_command": cmd.audit_command,
                "expected_output_regex": cmd.expected_output_regex,
                "expected_output_description": cmd.expected_output_description,
                "remediation_command": cmd.remediation_command,
                "status": cmd.status,
                "is_protected": cmd.is_protected,
            }
        else:
            entry["command"] = None
        results.append(entry)

    return {
        "total_matching": len(rules) if has_command is None else len(results),
        "showing": len(results),
        "rules": results,
    }


# Deep Quality Check


def deep_quality_check_handler(
    db: Session,
    benchmark_id: int,
    *,
    severity_filter: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Run full quality analysis: syntax, transport match, expression logic,
    confidence scoring, completeness, and platform best-practice checks.

    Returns a structured report with issues grouped by category, plus a
    ``commands_sample`` with representative commands for LLM commentary.
    """
    from backend.core.command_validator import validate_command, Issue

    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    platform_family = bm.platform_family if bm else "unknown"
    platform = (bm.platform or "").lower() if bm else ""

    query = db.query(Rule).filter(Rule.benchmark_id == benchmark_id)
    if severity_filter:
        query = query.filter(Rule.severity == severity_filter)
    rules = query.order_by(Rule.section_number).limit(limit).all()

    rule_ids = [r.id for r in rules]
    cmds = db.query(RuleCommand).filter(RuleCommand.rule_id.in_(rule_ids)).all() if rule_ids else []
    cmds_map = {c.rule_id: c for c in cmds}

    issues_list: list[dict[str, Any]] = []
    low_confidence: list[dict[str, Any]] = []
    review_suggestions: list[dict[str, Any]] = []
    commands_sample: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    total_analyzed = 0
    pass_count = 0
    warning_count = 0
    error_count = 0
    missing_commands = 0

    for rule in rules:
        cmd = cmds_map.get(rule.id)
        if not cmd or not cmd.audit_command:
            missing_commands += 1
            continue

        total_analyzed += 1
        transport = (cmd.command_transport or "shell").lower()
        expression = cmd.expected_output_regex or ""
        audit_cmd = cmd.audit_command
        title_lower = (rule.title or "").lower()
        rule_issues: list[Issue] = []

        # Layer 1: Static validation (syntax, shell-mix, basic expression checks)
        rule_issues.extend(validate_command(audit_cmd, transport, expression, rule.title))

        # Layer 2: Transport/platform alignment
        if platform_family in ("database",) and transport == "shell":
            has_sql_keywords = any(k in audit_cmd.upper() for k in ("SELECT", "SHOW", "EXEC"))
            if has_sql_keywords:
                rule_issues.append(Issue("warning", "transport_mismatch",
                                         "Command contains SQL keywords but uses shell transport"))

        if platform_family == "windows" and transport == "shell":
            if any(k in audit_cmd for k in ("grep ", "awk ", "/etc/", "/usr/")):
                rule_issues.append(Issue("error", "platform_mismatch",
                                         "Linux/Unix command on Windows platform"))
        elif platform_family == "linux" and transport == "powershell":
            rule_issues.append(Issue("error", "platform_mismatch",
                                     "PowerShell transport on Linux platform"))

        # Layer 3: Expression logic review
        if expression:
            # Tautology: expression always true (>=0 for numeric, contains: with empty)
            if expression.strip() in (">=0", ">= 0", ">=0.0"):
                rule_issues.append(Issue("warning", "expression_tautology",
                                         f"Expression '{expression}' is always true for non-negative values"))
            if expression.strip().startswith("contains:") and len(expression.strip()) <= len("contains:"):
                rule_issues.append(Issue("error", "empty_expression",
                                         "Empty 'contains:' value matches everything"))

            # Inversion: title says "disabled/denied" but expression checks for "enabled/allowed"
            disable_words = ("disable", "deny", "restrict", "prevent", "prohibit", "not allow")
            enable_words = ("enable", "allow", "permit", "accept")
            title_wants_off = any(w in title_lower for w in disable_words)
            title_wants_on = any(w in title_lower for w in enable_words)

            expr_lower = expression.lower()
            if title_wants_off and any(f"equals:{w}" in expr_lower or f"contains:{w}" in expr_lower
                                       for w in ("enabled", "yes", "true", "1", "allow", "permit", "on")):
                rule_issues.append(Issue("warning", "logic_inversion",
                                         f"Rule wants '{title_lower[:50]}' but expression checks for enabled/true"))
            elif title_wants_on and any(f"equals:{w}" in expr_lower or f"contains:{w}" in expr_lower
                                        for w in ("disabled", "no", "false", "0", "deny", "off")):
                rule_issues.append(Issue("warning", "logic_inversion",
                                         f"Rule wants '{title_lower[:50]}' but expression checks for disabled/false"))
        else:
            # No expression at all
            rule_issues.append(Issue("warning", "missing_expression",
                                     "No expected_output_regex defined — result cannot be evaluated"))

        # Layer 4: Command completeness
        if len(audit_cmd.strip()) < 5:
            rule_issues.append(Issue("error", "stub_command",
                                     f"Command too short to be valid: '{audit_cmd[:20]}'"))
        if audit_cmd.strip().lower() in ("todo", "tbd", "manual", "n/a", "not implemented"):
            rule_issues.append(Issue("error", "stub_command",
                                     f"Placeholder command: '{audit_cmd[:30]}'"))

        generic_expr = {".*", ".+", "^.*$", "^.+$", "equals:", "contains:"}
        if expression.strip() in generic_expr:
            rule_issues.append(Issue("warning", "generic_expression",
                                     f"Expression '{expression}' is too generic — matches almost anything"))

        # Layer 5: Platform best-practice checks
        if platform_family == "linux" and transport == "shell":
            # Commands should ideally use absolute paths
            first_token = audit_cmd.strip().split()[0] if audit_cmd.strip() else ""
            relative_tools = {"grep", "awk", "sed", "cat", "stat", "find", "systemctl",
                              "sysctl", "mount", "df", "ss", "ip", "modprobe", "lsmod",
                              "auditctl", "journalctl", "chkconfig", "ufw"}
            if first_token in relative_tools:
                review_suggestions.append({
                    "rule_id": rule.id,
                    "section_number": rule.section_number,
                    "suggestion": f"Consider absolute path for '{first_token}' (e.g. /usr/bin/{first_token})",
                })

        # Confidence scoring
        score = getattr(cmd, "confidence_score", None) or 0.5
        if score < 0.7:
            low_confidence.append({
                "rule_id": rule.id,
                "section_number": rule.section_number,
                "title": rule.title,
                "confidence_score": round(score, 2),
                "source": getattr(cmd, "confidence_source", None) or "unknown",
                "command_preview": audit_cmd[:80],
            })

        # Collect issues
        if not rule_issues:
            pass_count += 1
        else:
            for issue in rule_issues:
                sev = issue.severity
                if sev == "error":
                    error_count += 1
                else:
                    warning_count += 1
                category_counts[issue.category] = category_counts.get(issue.category, 0) + 1
                issues_list.append({
                    "rule_id": rule.id,
                    "section_number": rule.section_number,
                    "title": rule.title,
                    "severity": sev,
                    "category": issue.category,
                    "message": issue.message,
                    "command_preview": audit_cmd[:120],
                    "expression": expression[:80] if expression else None,
                    "confidence_score": getattr(cmd, "confidence_score", None),
                })

        # Sample commands for LLM commentary (pick a spread of issues/passing)
        if len(commands_sample) < 10:
            commands_sample.append({
                "rule_id": rule.id,
                "section_number": rule.section_number,
                "title": rule.title[:80],
                "audit_command": audit_cmd[:200],
                "expected_output_regex": expression[:100] if expression else None,
                "transport": transport,
                "confidence": round(score, 2),
                "issues_found": len(rule_issues),
            })

    # Build summary
    low_conf_total = len(low_confidence)
    parts = []
    if error_count:
        top_errors = sorted(category_counts.items(), key=lambda x: -x[1])[:3]
        parts.append(f"{error_count} error(s)")
        for cat, cnt in top_errors:
            parts.append(f"{cnt} {cat.replace('_', ' ')}")
    if warning_count:
        parts.append(f"{warning_count} warning(s)")
    if missing_commands:
        parts.append(f"{missing_commands} rule(s) without commands")
    if low_conf_total:
        parts.append(f"{low_conf_total} low-confidence command(s) needing review")
    summary = ". ".join(parts) if parts else f"All {pass_count} commands passed validation"

    return {
        "total_analyzed": total_analyzed,
        "pass": pass_count,
        "warnings": warning_count,
        "errors": error_count,
        "missing_commands": missing_commands,
        "by_category": category_counts,
        "issues": issues_list[:50],
        "low_confidence": low_confidence[:20],
        "low_confidence_total": low_conf_total,
        "review_suggestions": review_suggestions[:15],
        "commands_sample": commands_sample,
        "summary": summary,
    }


# Build tool registry (all handlers are defined above)

COPILOT_TOOLS.update({
    "search_rules": {
        "description": "Search existing rules across all benchmarks by text query",
        "handler": search_rules_handler,
    },
    "create_rule": {
        "description": "Create a new rule in the current benchmark (pending user approval)",
        "handler": create_rule_handler,
    },
    "create_rules_batch": {
        "description": "Create multiple rules at once (all pending user approval)",
        "handler": create_rules_batch_handler,
    },
    "edit_rule": {
        "description": "Edit an existing rule field",
        "handler": edit_rule_handler,
    },
    "edit_rules_batch": {
        "description": "Mass edit a field across multiple rules (staged for user approval)",
        "handler": edit_rules_batch_handler,
    },
    "explain_rule": {
        "description": "Generate a plain-English explanation of what a rule does and why it matters",
        "handler": explain_rule_handler,
    },
    "suggest_gaps": {
        "description": "Analyze current benchmark and suggest missing security coverage areas",
        "handler": suggest_gaps_handler,
    },
    "find_similar_rules": {
        "description": "Find rules in other benchmarks similar to a given description",
        "handler": find_similar_handler,
    },
    "get_rule_details": {
        "description": "Get full details of a specific rule including its command",
        "handler": get_rule_details_handler,
    },
    "count_rules": {
        "description": "Get rule counts and severity breakdown for current benchmark",
        "handler": count_rules_handler,
    },
    "generate_commands": {
        "description": "Generate audit commands for rules that don't have them",
        "handler": generate_commands_handler,
    },
    "list_rules": {
        "description": "List rules in the current benchmark with optional severity filter",
        "handler": list_rules_handler,
    },
    "get_benchmark_info": {
        "description": "Get benchmark metadata, pipeline status, and overall stats",
        "handler": get_benchmark_info_handler,
    },
    "import_rules_from_benchmark": {
        "description": "Import rules from another benchmark into the current one (pending approval)",
        "handler": import_rules_from_benchmark_handler,
    },
    # Pipeline Control
    "get_pipeline_status": {
        "description": "Get pipeline status for all phases and enrichment/validation stats",
        "handler": get_pipeline_status_handler,
    },
    "start_enrichment": {
        "description": "Start Phase 2 command enrichment in background",
        "handler": start_enrichment_handler,
    },
    "pause_enrichment": {
        "description": "Pause Phase 2 enrichment at next batch boundary",
        "handler": pause_enrichment_handler,
    },
    "start_verification": {
        "description": "Start command verification (syntax, safety, cross-reference checks)",
        "handler": start_verification_handler,
    },
    "start_validation": {
        "description": "Start Phase 3 LLM validation of commands",
        "handler": start_validation_handler,
    },
    # Command Management
    "verify_command": {
        "description": "Verify a single command with static checks (no live target needed)",
        "handler": verify_command_handler,
    },
    "edit_command": {
        "description": "Edit a command field (audit_command, expected_output_regex, etc.)",
        "handler": edit_command_handler,
    },
    "flag_command": {
        "description": "Flag a command with a reason for review or regeneration",
        "handler": flag_command_handler,
    },
    "regenerate_command": {
        "description": "Regenerate a flagged command using LLM with error context",
        "handler": regenerate_command_handler,
    },
    "get_command_history": {
        "description": "Get the history of previous commands for a rule",
        "handler": get_command_history_handler,
    },
    # Validation Review
    "get_validation_results": {
        "description": "Get Phase 3 validation corrections for the benchmark",
        "handler": get_validation_results_handler,
    },
    "apply_correction": {
        "description": "Apply Phase 3 LLM correction to a command",
        "handler": apply_correction_handler,
    },
    "dismiss_correction": {
        "description": "Dismiss a Phase 3 correction without applying",
        "handler": dismiss_correction_handler,
    },
    "bulk_apply_corrections": {
        "description": "Apply all high-confidence Phase 3 corrections at once",
        "handler": bulk_apply_corrections_handler,
    },
    # Intelligence
    "diff_benchmarks": {
        "description": "Compare this benchmark with another to find added/removed/modified rules",
        "handler": diff_benchmarks_handler,
    },
    "get_migration_readiness": {
        "description": "Check benchmark readiness for deployment with actionable recommendations",
        "handler": get_migration_readiness_handler,
    },
    "explain_phase2_behavior": {
        "description": "Explain how Phase 2 handles existing copilot-generated commands",
        "handler": explain_phase2_behavior_handler,
    },
    # Safe Delete
    "delete_rule": {
        "description": "Delete a copilot-created or pending rule (blocked for protected/verified rules)",
        "handler": delete_rule_handler,
    },
    # Inspect Commands (batch)
    "inspect_commands": {
        "description": "Inspect rules with their full commands in a batch (no individual rule IDs needed)",
        "handler": inspect_commands_handler,
    },
    # Deep Quality Analysis
    "deep_quality_check": {
        "description": "Run full quality analysis on all commands: syntax, transport match, expression logic, confidence scores",
        "handler": deep_quality_check_handler,
    },
})
