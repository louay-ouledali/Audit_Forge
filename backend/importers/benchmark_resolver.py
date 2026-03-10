"""Benchmark resolver — matches imported findings to existing benchmarks or creates new ones.

Two modes:
1. **Match**: Find an existing benchmark by name + version (fuzzy matching)
2. **Reconstruct**: Create a new benchmark from extracted rules (Nessus reverse engineering)

The resolver is source-agnostic — it works with any PlatformInfo + ExtractedRule list.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.importers.base import ExtractedRule, PlatformInfo
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule

logger = logging.getLogger("auditforge.importers.benchmark_resolver")


class ResolverResult:
    """Result of benchmark resolution."""

    def __init__(
        self,
        benchmark: Benchmark,
        *,
        created: bool = False,
        rules_matched: int = 0,
        rules_created: int = 0,
        migration_readiness: float = 0.0,
    ):
        self.benchmark = benchmark
        self.created = created
        self.rules_matched = rules_matched
        self.rules_created = rules_created
        self.migration_readiness = migration_readiness


def resolve_benchmark(
    platform_info: PlatformInfo,
    extracted_rules: list[ExtractedRule],
    db: Session,
    *,
    allow_create: bool = True,
) -> ResolverResult:
    """Find or create a benchmark matching the import data.

    Steps:
    1. Try exact match by name + version
    2. Try fuzzy match by name (closest version)
    3. If allow_create and no match found → reconstruct benchmark from rules
    4. If match found → count how many rules already exist

    Parameters
    ----------
    platform_info : PlatformInfo
        Auto-detected platform information.
    extracted_rules : list[ExtractedRule]
        Rules extracted from the import source (for reconstruction).
    db : Session
        Database session.
    allow_create : bool
        If True, create a new benchmark when no match is found.

    Returns
    -------
    ResolverResult
        Contains the benchmark and statistics.
    """
    benchmark = _try_exact_match(platform_info, db)
    if benchmark:
        rules_matched = _count_matching_rules(benchmark, extracted_rules, db)
        readiness = _calculate_migration_readiness(benchmark.id, db)
        logger.info("Exact match: benchmark '%s' v%s (id=%d, %d rules matched)",
                     benchmark.name, benchmark.version, benchmark.id, rules_matched)
        return ResolverResult(
            benchmark,
            rules_matched=rules_matched,
            migration_readiness=readiness,
        )

    benchmark = _try_fuzzy_match(platform_info, db)
    if benchmark:
        rules_matched = _count_matching_rules(benchmark, extracted_rules, db)
        readiness = _calculate_migration_readiness(benchmark.id, db)
        logger.info("Fuzzy match: benchmark '%s' v%s (id=%d, %d rules matched)",
                     benchmark.name, benchmark.version, benchmark.id, rules_matched)
        return ResolverResult(
            benchmark,
            rules_matched=rules_matched,
            migration_readiness=readiness,
        )

    if not allow_create:
        raise ValueError(
            f"No matching benchmark found for '{platform_info.benchmark_name}' "
            f"v{platform_info.benchmark_version} and creation is disabled."
        )

    # ── Reconstruct benchmark ──────────────────────────────────
    benchmark, rules_created = _reconstruct_benchmark(platform_info, extracted_rules, db)
    logger.info("Reconstructed benchmark '%s' v%s with %d rules",
                 benchmark.name, benchmark.version, rules_created)

    return ResolverResult(
        benchmark,
        created=True,
        rules_created=rules_created,
        migration_readiness=0.0,  # No validated commands yet
    )


def _try_exact_match(info: PlatformInfo, db: Session) -> Benchmark | None:
    """Try to find a benchmark with exact name + version match."""
    if not info.benchmark_name:
        return None

    q = db.query(Benchmark).filter(
        Benchmark.name.ilike(f"%{info.benchmark_name}%"),
        Benchmark.status != "deleted",
    )

    if info.benchmark_version:
        result = q.filter(Benchmark.version == info.benchmark_version).first()
        if result:
            return result

    return None


def _try_fuzzy_match(info: PlatformInfo, db: Session) -> Benchmark | None:
    """Try fuzzy matching: same name family, closest version.

    When no benchmark_name is available, skip fuzzy matching entirely —
    a platform-only search is too coarse and pulls in unrelated benchmarks
    whose rules don't match the import findings at all.
    """
    if not info.benchmark_name:
        # Never fuzzy-match by platform alone; prefer reconstruction so that
        # every imported finding gets a corresponding rule.
        return None

    # Extract the core product name (e.g., "Windows Server 2012 R2" from
    # "CIS Microsoft Windows Server 2012 R2 Benchmark")
    import re
    core_match = re.search(
        r"(?:CIS|NIST|STIG|DISA)\s+(?:Microsoft\s+)?(.*?)(?:\s+Benchmark)?$",
        info.benchmark_name,
        re.IGNORECASE,
    )
    search_term = core_match.group(1).strip() if core_match else info.benchmark_name

    candidates = (
        db.query(Benchmark)
        .filter(
            Benchmark.name.ilike(f"%{search_term}%"),
            Benchmark.status != "deleted",
        )
        .all()
    )

    if not candidates:
        return None

    # If we have a target version, pick the closest one
    if info.benchmark_version and len(candidates) > 1:
        target_parts = _version_tuple(info.benchmark_version)
        best = min(candidates, key=lambda b: _version_distance(target_parts, _version_tuple(b.version)))
        return best

    # Otherwise return the most recent
    return max(candidates, key=lambda b: b.import_date or datetime.min.replace(tzinfo=timezone.utc))


def _reconstruct_benchmark(
    info: PlatformInfo,
    extracted_rules: list[ExtractedRule],
    db: Session,
) -> tuple[Benchmark, int]:
    """Create a new benchmark and populate it with extracted rules."""

    name = info.benchmark_name or f"{info.platform or 'Unknown'} Compliance"
    version = info.benchmark_version or "imported"

    source_details = json.dumps({
        "import_source": info.source_tool,
        "auto_detected": True,
        "platform_info": info.to_dict(),
    })

    # Map scheme to framework
    _scheme_to_framework = {
        "CIS": "cis",
        "STIG": "stig",
        "NIST": "nist",
        "ISO": "iso",
        "SCAP": "xccdf",
    }
    framework = _scheme_to_framework.get(info.scheme, "unknown")

    benchmark = Benchmark(
        name=name,
        version=version,
        platform=info.platform or "Unknown",
        platform_family=info.platform_family or "Unknown",
        framework=framework,
        total_rules=len(extracted_rules),
        source="nessus_reconstructed" if info.source_tool == "nessus" else "imported",
        is_ready=False,       # Not ready until commands are generated
        status="active",
        phase1_status="completed",   # Rules are extracted
        phase2_status="pending",     # Commands need generation
        is_editable=True,
        source_details=source_details,
        migration_readiness=0.0,
    )
    db.add(benchmark)
    db.flush()  # Get the ID

    # Create rules
    rules_created = 0
    for extracted in extracted_rules:
        kwargs = extracted.to_rule_kwargs()
        kwargs["benchmark_id"] = benchmark.id
        kwargs["source"] = f"{info.source_tool}_import"

        # Store framework mappings as JSON
        if extracted.framework_mappings:
            kwargs["framework_mappings"] = json.dumps(extracted.framework_mappings)

        rule = Rule(**kwargs)
        db.add(rule)
        rules_created += 1

    db.flush()

    return benchmark, rules_created


def _count_matching_rules(
    benchmark: Benchmark,
    extracted_rules: list[ExtractedRule],
    db: Session,
) -> int:
    """Count how many extracted rules match existing rules in the benchmark."""
    if not extracted_rules:
        return 0

    sections = {r.section_number for r in extracted_rules if r.section_number}
    if not sections:
        return 0

    return (
        db.query(func.count(Rule.id))
        .filter(
            Rule.benchmark_id == benchmark.id,
            Rule.section_number.in_(sections),
        )
        .scalar()
        or 0
    )


def _calculate_migration_readiness(benchmark_id: int, db: Session) -> float:
    """Calculate the percentage of rules that have validated commands.

    Migration readiness = rules with at least a generated RuleCommand / total rules * 100
    """
    from backend.models.rule_command import RuleCommand

    total = db.query(func.count(Rule.id)).filter(Rule.benchmark_id == benchmark_id).scalar() or 0
    if total == 0:
        return 0.0

    with_commands = (
        db.query(func.count(RuleCommand.id))
        .join(Rule, Rule.id == RuleCommand.rule_id)
        .filter(Rule.benchmark_id == benchmark_id)
        .scalar()
        or 0
    )

    return round(with_commands / total * 100, 1)


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple."""
    import re
    parts = re.findall(r"\d+", version)
    return tuple(int(p) for p in parts) if parts else (0,)


def _version_distance(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """Calculate a simple distance between two version tuples."""
    max_len = max(len(a), len(b))
    a_padded = a + (0,) * (max_len - len(a))
    b_padded = b + (0,) * (max_len - len(b))
    return sum(abs(x - y) * (1000 ** (max_len - i)) for i, (x, y) in enumerate(zip(a_padded, b_padded)))
