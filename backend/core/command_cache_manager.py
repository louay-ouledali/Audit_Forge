"""Command cache manager — cross-benchmark command reuse engine.

Provides CRUD operations, confidence-scored lookups, and title-similarity
matching for the global ``command_cache`` table.  Used by Phase 2
(command generation) to skip LLM calls for rules already seen in other
benchmark versions or frameworks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from backend.models.benchmark import Benchmark
from backend.models.command_cache import CommandCache, make_cache_key, normalize_title
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand

logger = logging.getLogger("auditforge.core.command_cache_manager")


#  Title similarity

def _jaccard_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two normalised titles."""
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


#  Populate cache from a completed benchmark

def populate_cache_from_benchmark(db: Session, benchmark_id: int) -> dict[str, int]:
    """Populate the command cache from all rules with commands in a benchmark.

    Called after Phase 2 or Phase 3 completion.  Only inserts entries that
    don't already exist (by cache_key + platform).

    Returns stats: {inserted, skipped, total}.
    """
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        return {"inserted": 0, "skipped": 0, "total": 0}

    rules = (
        db.query(Rule, RuleCommand)
        .join(RuleCommand, RuleCommand.rule_id == Rule.id)
        .filter(Rule.benchmark_id == benchmark_id)
        .filter(RuleCommand.audit_command.isnot(None))
        .filter(RuleCommand.audit_command != "")
        .all()
    )

    inserted = 0
    skipped = 0

    for rule, cmd in rules:
        key = make_cache_key(benchmark.platform, rule.section_number, rule.title)

        existing = (
            db.query(CommandCache)
            .filter(
                CommandCache.cache_key == key,
                CommandCache.platform == benchmark.platform,
            )
            .first()
        )

        if existing:
            # Update verification status if the source is more authoritative
            if cmd.validation_status == "validated" and existing.verification_status != "verified":
                existing.verification_status = "verified"
            skipped += 1
            continue

        verification = "unverified"
        if cmd.validation_status == "validated":
            verification = "verified"
        elif cmd.validation_status == "flagged":
            verification = "flagged"

        entry = CommandCache(
            cache_key=key,
            platform=benchmark.platform,
            platform_family=benchmark.platform_family,
            section_number=rule.section_number,
            rule_title_normalized=normalize_title(rule.title),
            audit_command=cmd.audit_command,
            expected_output_regex=cmd.expected_output_regex,
            expected_output_description=cmd.expected_output_description,
            remediation_command=cmd.remediation_command,
            remediation_description=cmd.remediation_description,
            source_benchmark_id=benchmark.id,
            source_framework=benchmark.framework or "cis",
            confidence=1.0,
            match_type="exact_version",
            verification_status=verification,
        )
        db.add(entry)
        inserted += 1

    db.flush()
    logger.info(
        "Cache populated from benchmark %s: %d inserted, %d skipped",
        benchmark.name,
        inserted,
        skipped,
    )
    return {"inserted": inserted, "skipped": skipped, "total": len(rules)}


#  Lookup commands for a benchmark entering Phase 2

def lookup_commands_for_benchmark(
    db: Session,
    benchmark_id: int,
    *,
    min_confidence: float = 0.5,
    cross_framework: bool = True,
) -> list[dict[str, Any]]:
    """Find cached commands for rules in a benchmark that lack commands.

    Returns a list of dicts:
      {rule_id, section_number, cache_entry_id, confidence, match_type,
       audit_command, expected_output_regex, ...}

    The caller decides which to auto-import vs flag for review.
    """
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        return []

    # Rules that need commands
    rules_needing = (
        db.query(Rule)
        .outerjoin(RuleCommand, RuleCommand.rule_id == Rule.id)
        .filter(
            Rule.benchmark_id == benchmark_id,
            (RuleCommand.id.is_(None)) | (RuleCommand.audit_command.is_(None)) | (RuleCommand.audit_command == ""),
        )
        .all()
    )

    if not rules_needing:
        return []

    # All cache entries for this exact platform
    cache_query = db.query(CommandCache).filter(
        CommandCache.platform == benchmark.platform,
        CommandCache.audit_command.isnot(None),
        CommandCache.audit_command != "",
    )
    if not cross_framework:
        cache_query = cache_query.filter(
            CommandCache.source_framework == (benchmark.framework or "cis")
        )

    cache_entries = cache_query.all()
    if not cache_entries:
        return []

    # Build lookup indexes
    by_section: dict[str, list[CommandCache]] = {}
    by_title: list[CommandCache] = []
    for entry in cache_entries:
        by_section.setdefault(entry.section_number, []).append(entry)
        by_title.append(entry)

    results: list[dict[str, Any]] = []

    for rule in rules_needing:
        best_match: dict[str, Any] | None = None
        best_confidence = 0.0

        norm_title = normalize_title(rule.title)

        # Strategy 1: Exact section_number match
        if rule.section_number in by_section:
            for entry in by_section[rule.section_number]:
                title_sim = _jaccard_similarity(norm_title, entry.rule_title_normalized)

                # Same framework, same section
                if entry.source_framework == (benchmark.framework or "cis"):
                    if entry.source_benchmark_id != benchmark.id:
                        conf = 0.9  # cross-version
                    else:
                        conf = 1.0
                else:
                    # Cross-framework
                    if title_sim > 0.85:
                        conf = 0.7
                    elif title_sim > 0.6:
                        conf = 0.5
                    else:
                        continue  # Too dissimilar

                # Boost if expected_output_regex matches exactly
                if entry.verification_status == "verified":
                    conf = min(conf + 0.05, 1.0)

                if conf > best_confidence:
                    best_confidence = conf
                    best_match = _entry_to_dict(entry, rule, conf, "cross_version" if conf >= 0.9 else "cross_framework")

        # Strategy 2: Title-only match (no section_number)
        if best_confidence < 0.7:
            for entry in by_title:
                title_sim = _jaccard_similarity(norm_title, entry.rule_title_normalized)
                if title_sim < 0.85:
                    continue

                conf = 0.5
                if entry.source_framework == (benchmark.framework or "cis"):
                    conf = 0.6

                if conf > best_confidence:
                    best_confidence = conf
                    best_match = _entry_to_dict(entry, rule, conf, "cross_framework")

        if best_match and best_confidence >= min_confidence:
            results.append(best_match)

    logger.info(
        "Cache lookup for benchmark %s: %d/%d rules matched (min_confidence=%.2f)",
        benchmark.name,
        len(results),
        len(rules_needing),
        min_confidence,
    )
    return results


def _entry_to_dict(entry: CommandCache, rule: Rule, confidence: float, match_type: str) -> dict[str, Any]:
    """Convert a cache entry + rule into a result dict."""
    return {
        "rule_id": rule.id,
        "section_number": rule.section_number,
        "cache_entry_id": entry.id,
        "confidence": round(confidence, 3),
        "match_type": match_type,
        "audit_command": entry.audit_command,
        "expected_output_regex": entry.expected_output_regex,
        "expected_output_description": entry.expected_output_description,
        "remediation_command": entry.remediation_command,
        "remediation_description": entry.remediation_description,
        "source_framework": entry.source_framework,
        "source_benchmark_id": entry.source_benchmark_id,
        "verification_status": entry.verification_status,
    }


#  Strict platform lookup (for unknown benchmarks — Feature 3)

def strict_platform_lookup(
    db: Session,
    platform: str,
    rules: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Look up cached commands using STRICT exact platform matching.

    Used for unknown/reverse-engineered benchmarks.  Only returns results if
    ``platform`` matches EXACTLY (normalised lowercase comparison).  No fuzzy
    platform matching — "Windows 11" won't match "Windows Server 2022".

    Args:
        platform: Exact platform string (e.g. "Windows 11 Enterprise").
        rules: List of dicts with keys ``section_number`` and ``title``.

    Returns list of match dicts (same shape as ``lookup_commands_for_benchmark``).
    """
    norm_platform = platform.strip().lower()

    cache_entries = (
        db.query(CommandCache)
        .filter(
            func.lower(CommandCache.platform) == norm_platform,
            CommandCache.audit_command.isnot(None),
            CommandCache.audit_command != "",
        )
        .all()
    )

    if not cache_entries:
        logger.info("Strict platform lookup: no cache entries for platform '%s'", platform)
        return []

    # Build section index
    by_section: dict[str, list[CommandCache]] = {}
    for entry in cache_entries:
        by_section.setdefault(entry.section_number, []).append(entry)

    results: list[dict[str, Any]] = []

    for rule_dict in rules:
        section = rule_dict.get("section_number", "")
        title = rule_dict.get("title", "")
        norm_title = normalize_title(title)

        if section not in by_section:
            continue

        for entry in by_section[section]:
            title_sim = _jaccard_similarity(norm_title, entry.rule_title_normalized)
            if title_sim < 0.85:
                continue

            conf = 0.7  # cross-framework base for unknown benchmarks
            if entry.verification_status == "verified":
                conf = 0.75

            results.append({
                "section_number": section,
                "title": title,
                "cache_entry_id": entry.id,
                "confidence": round(conf, 3),
                "match_type": "cross_framework",
                "audit_command": entry.audit_command,
                "expected_output_regex": entry.expected_output_regex,
                "expected_output_description": entry.expected_output_description,
                "remediation_command": entry.remediation_command,
                "remediation_description": entry.remediation_description,
                "source_framework": entry.source_framework,
                "source_benchmark_id": entry.source_benchmark_id,
                "verification_status": entry.verification_status,
            })
            break  # Take first good match per rule

    logger.info(
        "Strict platform lookup for '%s': %d/%d rules matched",
        platform,
        len(results),
        len(rules),
    )
    return results


#  Apply cached commands to a benchmark

def apply_cached_commands(
    db: Session,
    matches: list[dict[str, Any]],
    *,
    auto_import_threshold: float = 0.9,
    flag_threshold: float = 0.7,
) -> dict[str, int]:
    """Apply a list of cache lookup results to rules.

    - confidence >= auto_import_threshold: create RuleCommand with status="inherited"
    - confidence >= flag_threshold: create RuleCommand with status="review_needed"
    - below flag_threshold: skip

    Returns stats: {auto_imported, flagged, skipped}.
    """
    auto_imported = 0
    flagged = 0
    skipped = 0

    for match in matches:
        conf = match["confidence"]
        rule_id = match.get("rule_id")

        if not rule_id:
            skipped += 1
            continue

        if conf < flag_threshold:
            skipped += 1
            continue

        # Check if rule already has a command
        existing = db.query(RuleCommand).filter(RuleCommand.rule_id == rule_id).first()
        if existing and existing.audit_command:
            skipped += 1
            continue

        if conf >= auto_import_threshold:
            status = "inherited"
            source = "cache_auto"
        else:
            status = "review_needed"
            source = "cache_review"

        if existing:
            existing.audit_command = match["audit_command"]
            existing.expected_output_regex = match["expected_output_regex"]
            existing.expected_output_description = match.get("expected_output_description")
            existing.remediation_command = match.get("remediation_command")
            existing.remediation_description = match.get("remediation_description")
            existing.command_transport = match.get("command_transport") or existing.command_transport
            existing.status = status
            existing.source = source
            existing.updated_at = datetime.now(timezone.utc)
        else:
            cmd = RuleCommand(
                rule_id=rule_id,
                audit_command=match["audit_command"],
                command_transport=match.get("command_transport"),
                expected_output_regex=match["expected_output_regex"],
                expected_output_description=match.get("expected_output_description"),
                remediation_command=match.get("remediation_command"),
                remediation_description=match.get("remediation_description"),
                status=status,
                source=source,
            )
            db.add(cmd)

        # Update cache hit count
        cache_entry = db.query(CommandCache).filter(CommandCache.id == match["cache_entry_id"]).first()
        if cache_entry:
            cache_entry.hit_count = (cache_entry.hit_count or 0) + 1
            cache_entry.last_used_at = datetime.now(timezone.utc)

        if conf >= auto_import_threshold:
            auto_imported += 1
        else:
            flagged += 1

    db.flush()
    logger.info(
        "Applied cached commands: %d auto-imported, %d flagged for review, %d skipped",
        auto_imported,
        flagged,
        skipped,
    )
    return {"auto_imported": auto_imported, "flagged": flagged, "skipped": skipped}


#  Cache statistics

def get_cache_stats(db: Session, platform: str | None = None) -> dict[str, Any]:
    """Return cache statistics, optionally filtered by platform."""
    query = db.query(CommandCache)
    if platform:
        query = query.filter(CommandCache.platform == platform)

    total = query.count()
    verified = query.filter(CommandCache.verification_status == "verified").count()
    total_hits = db.query(func.sum(CommandCache.hit_count)).scalar() or 0

    frameworks = (
        db.query(CommandCache.source_framework, func.count(CommandCache.id))
        .group_by(CommandCache.source_framework)
    )
    if platform:
        frameworks = frameworks.filter(CommandCache.platform == platform)
    framework_dist = {row[0]: row[1] for row in frameworks.all()}

    return {
        "total_entries": total,
        "verified_entries": verified,
        "total_hits": total_hits,
        "framework_distribution": framework_dist,
    }


def update_cache_entry(db: Session, cmd: Any, rule: Any) -> None:
    """Update or create a cache entry when an auditor edits a command.

    This keeps the cache in sync with manual edits so future benchmarks
    get the corrected version.
    """
    benchmark = db.query(Benchmark).filter(Benchmark.id == rule.benchmark_id).first()
    if not benchmark:
        return
    platform = benchmark.platform or ""
    title = rule.title or ""
    key = make_cache_key(title, rule.section_number or "")

    existing = (
        db.query(CommandCache)
        .filter(CommandCache.cache_key == key, CommandCache.platform == platform)
        .first()
    )
    if existing:
        existing.audit_command = cmd.audit_command
        existing.expected_output_regex = cmd.expected_output_regex or existing.expected_output_regex
        existing.command_transport = cmd.command_transport or existing.command_transport
        existing.updated_at = datetime.now(timezone.utc)
        logger.info("Updated cache entry %s for platform=%s", key, platform)
    else:
        entry = CommandCache(
            cache_key=key,
            platform=platform,
            section_number=rule.section_number or "",
            title=title,
            normalized_title=normalize_title(title),
            audit_command=cmd.audit_command,
            expected_output_regex=cmd.expected_output_regex or "",
            command_transport=cmd.command_transport,
            source_benchmark_id=benchmark.id,
            source_framework="manual",
        )
        db.add(entry)
        logger.info("Created cache entry %s for platform=%s", key, platform)
