"""Backfill benchmark_groups and command_cache from existing data.

Run after the Alembic migration ``p1h2a3s4e5_1`` to populate:
  1. benchmark_groups — group existing benchmarks by product_base + platform
  2. benchmarks.group_id — link each benchmark to its group
  3. benchmarks.framework — set "cis" on all existing benchmarks
  4. benchmarks.is_baseline — pick the best version per group
  5. command_cache — populate from all rule_commands with audit_command

Usage:
    cd backend
    python -m scripts.backfill_groups_and_cache
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

# Ensure the backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.benchmark import Benchmark
from backend.models.benchmark_group import BenchmarkGroup
from backend.core.command_cache_manager import populate_cache_from_benchmark

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill")


#  Product-base extraction (mirrors severity_enricher._extract_product_info)

def _extract_canonical_name(name: str) -> str:
    """Extract a canonical group name from a benchmark name.

    Strips version numbers but keeps the product identity.

    Examples:
        "CIS Microsoft Windows Server 2022 Benchmark"    → "CIS Windows Server 2022"
        "CIS Microsoft Windows 11 Enterprise Benchmark"  → "CIS Windows 11 Enterprise"
        "CIS Red Hat Enterprise Linux 9 Benchmark"       → "CIS Red Hat Enterprise Linux 9"
        "CIS PostgreSQL 16 Benchmark"                    → "CIS PostgreSQL 16"
    """
    cleaned = name.strip()
    # Remove " Benchmark" suffix
    cleaned = re.sub(r"\s+Benchmark\s*$", "", cleaned, flags=re.IGNORECASE)
    # Remove "Microsoft " (redundant with product name)
    cleaned = re.sub(r"\bMicrosoft\s+(?=Windows|SQL|Azure|Office|365)", "", cleaned, flags=re.IGNORECASE)
    # Remove version like "v1.0.0", "v2.6.0" at end
    cleaned = re.sub(r"\s+v?\d+\.\d+(\.\d+)?\s*$", "", cleaned)
    return cleaned.strip()


#  Main backfill logic

def backfill_groups(db: Session) -> dict[str, int]:
    """Create benchmark_groups and link existing benchmarks."""
    benchmarks = db.query(Benchmark).all()
    logger.info("Found %d existing benchmarks", len(benchmarks))

    groups_created = 0
    benchmarks_linked = 0

    # Group benchmarks by (canonical_name, platform)
    grouping: dict[tuple[str, str], list[Benchmark]] = {}
    for b in benchmarks:
        canonical = _extract_canonical_name(b.name)
        key = (canonical, b.platform)
        grouping.setdefault(key, []).append(b)

    for (canonical, platform), members in grouping.items():
        # Check if group already exists
        existing = (
            db.query(BenchmarkGroup)
            .filter(
                BenchmarkGroup.canonical_name == canonical,
                BenchmarkGroup.platform == platform,
            )
            .first()
        )
        if not existing:
            group = BenchmarkGroup(
                canonical_name=canonical,
                platform=platform,
                platform_family=members[0].platform_family,
                framework=members[0].framework or "cis",
            )
            db.add(group)
            db.flush()
            groups_created += 1
        else:
            group = existing

        # Link all members
        for b in members:
            b.group_id = group.id
            if not b.framework:
                b.framework = "cis"
            benchmarks_linked += 1

        # Pick baseline: prefer preloaded, then most rules, then most recent
        members_sorted = sorted(
            members,
            key=lambda x: (
                x.source == "preloaded",
                x.total_rules or 0,
                x.import_date or "",
            ),
            reverse=True,
        )
        for m in members:
            m.is_baseline = False
        members_sorted[0].is_baseline = True

    db.commit()
    logger.info("Groups created: %d, benchmarks linked: %d", groups_created, benchmarks_linked)
    return {"groups_created": groups_created, "benchmarks_linked": benchmarks_linked}


def backfill_command_cache(db: Session) -> dict[str, int]:
    """Populate command_cache from all existing rule_commands."""
    benchmarks = db.query(Benchmark).all()
    total_inserted = 0
    total_skipped = 0

    for b in benchmarks:
        stats = populate_cache_from_benchmark(db, b.id)
        total_inserted += stats["inserted"]
        total_skipped += stats["skipped"]

    db.commit()
    logger.info("Command cache: %d inserted, %d skipped", total_inserted, total_skipped)
    return {"inserted": total_inserted, "skipped": total_skipped}


def main() -> None:
    logger.info("Starting Phase 1 backfill...")
    db = SessionLocal()
    try:
        logger.info("=== Step 1: Backfill benchmark groups ===")
        group_stats = backfill_groups(db)

        logger.info("=== Step 2: Backfill command cache ===")
        cache_stats = backfill_command_cache(db)

        logger.info("=== Backfill complete ===")
        logger.info("  Groups: %d created", group_stats["groups_created"])
        logger.info("  Benchmarks linked: %d", group_stats["benchmarks_linked"])
        logger.info("  Cache entries: %d inserted, %d skipped", cache_stats["inserted"], cache_stats["skipped"])
    finally:
        db.close()


if __name__ == "__main__":
    main()
