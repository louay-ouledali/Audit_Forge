"""Pre-loaded benchmark pack loader.

Handles loading curated ``.auditforge.json`` packs from ``backend/preloaded/``
into the database at startup. Pre-loaded benchmarks are immediately ready to
scan — no LLM, no Phase 1/2/3 pipeline needed.

Lifecycle
---------
1. ``scan_preloaded_dir()`` reads ``manifest.json`` and discovers packs.
2. ``sync_preloaded(db)`` compares manifest entries against the DB:
   - **New** pack → ``load_pack()``
   - **Updated** pack (hash mismatch) → ``upgrade_pack()``
   - **Unchanged** pack → skip
3. ``main.py`` calls ``sync_preloaded(db)`` once at FastAPI startup.

Design decisions
~~~~~~~~~~~~~~~~
- All operations happen in a **single SQLAlchemy session per pack** so a
  failure rolls back cleanly without leaving partial data.
- Each pack is loaded inside its own ``try/except`` so one bad pack doesn't
  block the others.
- The manifest uses SHA-256 hashes of the JSON files for change detection —
  no need to parse the whole pack just to check freshness.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.rule_tag import RuleTag
from backend.schemas.preloaded import (
    PreloadedBenchmarkPack,
    PreloadedRule,
)

from backend.frozen_paths import PRELOADED_DIR

logger = logging.getLogger("auditforge.preloaded")

# Directory that houses manifest.json and all .auditforge.json packs
MANIFEST_PATH = PRELOADED_DIR / "manifest.json"


#  Data structures


@dataclass
class PackInfo:
    """Metadata for a single pack entry in the manifest."""

    filename: str
    benchmark_name: str
    version: str
    platform_family: str
    sha256: str
    path: Path

    @property
    def full_path(self) -> Path:
        return PRELOADED_DIR / self.filename


#  Manifest scanning


def compute_file_hash(path: Path) -> str:
    """Return the hex-encoded SHA-256 digest of *path*."""
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def scan_preloaded_dir() -> list[PackInfo]:
    """Read ``manifest.json`` and return a list of :class:`PackInfo` objects.

    Skips entries whose files are missing on disk and logs a warning.
    """
    if not MANIFEST_PATH.exists():
        logger.warning("No manifest.json found at %s — skipping preloaded sync", MANIFEST_PATH)
        return []

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read manifest.json: %s", exc)
        return []

    packs: list[PackInfo] = []
    for entry in manifest.get("packs", []):
        filename = entry.get("filename", "")
        pack_path = PRELOADED_DIR / filename
        if not pack_path.exists():
            logger.warning("Manifest references '%s' but file not found — skipping", filename)
            continue
        packs.append(PackInfo(
            filename=filename,
            benchmark_name=entry.get("benchmark_name", ""),
            version=entry.get("version", ""),
            platform_family=entry.get("platform_family", ""),
            sha256=entry.get("sha256", ""),
            path=pack_path,
        ))

    logger.info("Discovered %d preloaded pack(s) in manifest", len(packs))
    return packs


#  Pack → DB insertion


def _json_dumps(value: Any) -> str | None:
    """Convert a Python list/dict to a JSON string for storage in a Text column."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _insert_rule(db: Session, benchmark_id: int, rule_data: PreloadedRule) -> Rule:
    """Create a Rule + RuleCommand + RuleTags from a :class:`PreloadedRule`."""

    rule = Rule(
        benchmark_id=benchmark_id,
        section_number=rule_data.section_number,
        title=rule_data.title,
        description=rule_data.description,
        rationale=rule_data.rationale,
        profile_applicability=_json_dumps(rule_data.profile_applicability),
        assessment_type=rule_data.assessment_type,
        default_value=rule_data.default_value,
        severity=rule_data.severity,
        cis_controls=rule_data.cis_controls,
        enabled=rule_data.enabled,
        # Multi-framework support (schema v2.0)
        framework_ref=rule_data.framework_ref,
        # Pre-loaded intelligence fields on Rule
        narrative_group=rule_data.narrative_group,
        security_themes_json=_json_dumps(rule_data.security_themes),
        attack_chain_tags_json=_json_dumps(rule_data.attack_chain_tags),
        mitre_attack_json=_json_dumps(rule_data.mitre_attack),
        risk_weight=rule_data.risk_weight,
        related_rules_json=_json_dumps(rule_data.related_rules),
        group_with_json=_json_dumps(rule_data.group_with),
    )
    db.add(rule)
    db.flush()  # get rule.id

    # RuleCommand
    cmd = RuleCommand(
        rule_id=rule.id,
        audit_command=rule_data.audit_command,
        command_transport=rule_data.command_transport,
        expected_output_regex=rule_data.expected_output_expression,
        expected_output_description=rule_data.expected_output_description,
        remediation_command=rule_data.remediation_command,
        remediation_description=rule_data.remediation_description,
        status="curated",
        source="preloaded",
        # Pre-loaded intelligence fields on RuleCommand
        empty_output_interpretation=rule_data.empty_output_interpretation,
        output_value_map_json=_json_dumps(
            rule_data.output_value_map if rule_data.output_value_map else None
        ),
        fp_conditions_json=_json_dumps(
            [c.model_dump() for c in rule_data.fp_conditions] if rule_data.fp_conditions else None
        ),
        remediation_gpo_path=rule_data.remediation_gpo_path,
        remediation_risk=rule_data.remediation_risk,
        safe_to_automate=rule_data.safe_to_automate,
        requires_restart=rule_data.requires_restart,
        confidence_score=0.80,
        confidence_source="curated",
    )
    db.add(cmd)

    # RuleTags
    for tag in rule_data.tags:
        db.add(RuleTag(rule_id=rule.id, tag_id=tag.tag_id, source=tag.source))

    return rule


def load_pack(pack_path: Path, db: Session, *, pack_hash: str | None = None) -> Benchmark:
    """Parse a ``.auditforge.json`` file and insert it as a complete benchmark.

    Parameters
    ----------
    pack_path : Path
        Absolute path to the pack JSON file.
    db : Session
        Active SQLAlchemy session.  The caller should commit or rollback.
    pack_hash : str | None
        Pre-computed SHA-256 hash.  Computed on-the-fly if not supplied.

    Returns
    -------
    Benchmark
        The newly created SQLAlchemy :class:`Benchmark` instance (already
        flushed, with ``id`` populated).
    """
    raw = pack_path.read_text(encoding="utf-8")
    pack = PreloadedBenchmarkPack.model_validate_json(raw)

    if pack_hash is None:
        pack_hash = compute_file_hash(pack_path)

    meta = pack.benchmark
    logger.info(
        "Loading preloaded pack: %s v%s (%d rules)",
        meta.name, meta.version, meta.total_rules,
    )
    if meta.connection_hints:
        logger.info("  Connection hints: %s", meta.connection_hints)

    benchmark = Benchmark(
        name=meta.name,
        version=meta.version,
        platform=meta.platform,
        platform_family=meta.platform_family,
        framework=getattr(meta, "framework", "cis"),
        pdf_hash=meta.cis_pdf_hash.removeprefix("sha256:") if meta.cis_pdf_hash else None,
        total_rules=meta.total_rules,
        # Pre-loaded benchmarks skip the Phase 1/2/3 pipeline entirely
        phase1_status="completed",
        phase2_status="completed",
        verification_status="completed",
        is_ready=True,
        status="active",
        source="preloaded",
        is_editable=True,
        preloaded_version=meta.version,
        pack_hash=pack_hash,
        connection_hints=_json_dumps(meta.connection_hints),
    )
    db.add(benchmark)
    db.flush()  # get benchmark.id

    for rule_data in pack.rules:
        _insert_rule(db, benchmark.id, rule_data)

    logger.info(
        "  Loaded benchmark id=%d: %d rules inserted",
        benchmark.id, meta.total_rules,
    )
    return benchmark


#  Pack upgrade (replace existing benchmark with updated pack)


def upgrade_pack(
    existing_benchmark: Benchmark,
    pack_path: Path,
    db: Session,
    *,
    pack_hash: str | None = None,
) -> Benchmark:
    """Upgrade an existing preloaded benchmark with a newer pack.

    This is a **destructive replace**: the old rules/commands/tags are deleted
    and replaced with the new pack's data.  If scans or findings reference
    this benchmark, the upgrade is skipped to preserve user data (only the
    pack_hash is updated so we don't retry every startup).
    """
    raw = pack_path.read_text(encoding="utf-8")
    pack = PreloadedBenchmarkPack.model_validate_json(raw)

    if pack_hash is None:
        pack_hash = compute_file_hash(pack_path)

    meta = pack.benchmark

    # Guard: skip destructive replace if user scan data references this benchmark
    from backend.models.scan import Scan
    from backend.models.finding import Finding
    scan_count = db.query(Scan).filter(Scan.benchmark_id == existing_benchmark.id).count()
    finding_count = (
        db.query(Finding)
        .join(Scan, Finding.scan_id == Scan.id)
        .filter(Scan.benchmark_id == existing_benchmark.id)
        .count()
    )
    if scan_count > 0 or finding_count > 0:
        logger.warning(
            "Skipping destructive upgrade of benchmark id=%d (%s): "
            "%d scans / %d findings would be lost. Updating hash only.",
            existing_benchmark.id, meta.name, scan_count, finding_count,
        )
        existing_benchmark.pack_hash = pack_hash
        existing_benchmark.connection_hints = _json_dumps(meta.connection_hints)
        return existing_benchmark

    logger.info(
        "Upgrading preloaded benchmark id=%d: %s v%s -> v%s (%d rules)",
        existing_benchmark.id, meta.name, existing_benchmark.version,
        meta.version, meta.total_rules,
    )

    # Delete all existing rules (cascade deletes commands + tags)
    db.query(Rule).filter(Rule.benchmark_id == existing_benchmark.id).delete()
    db.flush()

    # Update benchmark metadata
    existing_benchmark.name = meta.name
    existing_benchmark.version = meta.version
    existing_benchmark.platform = meta.platform
    existing_benchmark.platform_family = meta.platform_family
    existing_benchmark.framework = getattr(meta, "framework", "cis")
    existing_benchmark.total_rules = meta.total_rules
    existing_benchmark.pack_hash = pack_hash
    existing_benchmark.preloaded_version = meta.version
    existing_benchmark.connection_hints = _json_dumps(meta.connection_hints)
    existing_benchmark.phase1_status = "completed"
    existing_benchmark.phase2_status = "completed"
    existing_benchmark.verification_status = "completed"
    existing_benchmark.is_ready = True

    # Insert new rules
    for rule_data in pack.rules:
        _insert_rule(db, existing_benchmark.id, rule_data)

    logger.info(
        "  Upgraded benchmark id=%d: %d rules replaced",
        existing_benchmark.id, meta.total_rules,
    )
    return existing_benchmark


#  Duplicate cleanup — remove preloaded copies when a user-imported version exists


def _cleanup_preloaded_duplicates(db: Session) -> int:
    """Delete preloaded benchmarks that duplicate a user-imported benchmark.

    This can happen when the preloaded sync ran before it checked for
    user-imported benchmarks by the same name.  The user-imported (enriched)
    version always takes precedence.

    Returns the number of duplicates removed.
    """
    from sqlalchemy import func

    # Sub-query: names that exist as both 'preloaded' and 'user_imported'
    user_names = (
        db.query(Benchmark.name)
        .filter(Benchmark.source != "preloaded")
        .subquery()
    )
    dupes = (
        db.query(Benchmark)
        .filter(
            Benchmark.source == "preloaded",
            Benchmark.name.in_(db.query(user_names.c.name)),
        )
        .all()
    )

    if not dupes:
        return 0

    from backend.models.scan import Scan
    from backend.models.target import Target

    for b in dupes:
        logger.info(
            "Removing duplicate preloaded benchmark id=%d '%s' (user-imported copy exists)",
            b.id, b.name,
        )
        # Null out FK references so they don't become stale after deletion
        db.query(Scan).filter(Scan.benchmark_id == b.id).update(
            {"benchmark_id": None}, synchronize_session="fetch"
        )
        db.query(Target).filter(Target.default_benchmark_id == b.id).update(
            {"default_benchmark_id": None}, synchronize_session="fetch"
        )
        db.delete(b)  # cascades to rules → commands → tags

    db.commit()
    logger.info("Cleaned up %d duplicate preloaded benchmarks", len(dupes))
    return len(dupes)


#  Sync engine — called at startup


def sync_preloaded(db: Session) -> dict[str, int]:
    """Synchronise preloaded packs from disk into the database.

    Behaviour
    ---------
    | Scenario | Action |
    |----------|--------|
    | Pack in manifest, not in DB | ``load_pack()`` |
    | Pack in manifest, same hash in DB | Skip (already loaded) |
    | Pack in manifest, different hash in DB | ``upgrade_pack()`` |
    | Benchmark in DB, not in manifest | Leave alone (user-imported) |

    Returns
    -------
    dict
        Summary counts: ``{"loaded": N, "upgraded": N, "skipped": N, "errors": N}``
    """
    packs = scan_preloaded_dir()
    stats = {"loaded": 0, "upgraded": 0, "skipped": 0, "errors": 0}

    if not packs:
        logger.info("No preloaded packs to sync")
        return stats

    # Phase 0: remove preloaded duplicates of user-imported benchmarks
    _cleanup_preloaded_duplicates(db)

    for pack_info in packs:
        try:
            disk_hash = compute_file_hash(pack_info.full_path)

            # Find ANY existing benchmark with the same name (regardless of source).
            # A user-imported benchmark with the same name means the pack is
            # already covered — we must not create a second copy.
            existing = (
                db.query(Benchmark)
                .filter(Benchmark.name == pack_info.benchmark_name)
                .first()
            )

            if existing is not None:
                # If a user-imported benchmark has the same name, skip entirely
                # — the user's enriched version takes precedence.
                if existing.source != "preloaded":
                    # Backfill connection_hints for user-imported benchmarks
                    if not existing.connection_hints:
                        try:
                            raw = pack_info.full_path.read_text(encoding="utf-8")
                            _pack = PreloadedBenchmarkPack.model_validate_json(raw)
                            hints = _json_dumps(_pack.benchmark.connection_hints)
                            if hints:
                                existing.connection_hints = hints
                                db.commit()
                                logger.info("  Backfilled connection_hints for '%s'", pack_info.filename)
                        except Exception:
                            pass  # non-critical backfill
                    logger.debug(
                        "  Pack '%s' already covered by %s benchmark id=%d — skipping",
                        pack_info.filename, existing.source, existing.id,
                    )
                    stats["skipped"] += 1
                    continue

                if existing.pack_hash == disk_hash:
                    # Backfill connection_hints for packs synced before the column existed
                    if not existing.connection_hints:
                        try:
                            raw = pack_info.full_path.read_text(encoding="utf-8")
                            _pack = PreloadedBenchmarkPack.model_validate_json(raw)
                            hints = _json_dumps(_pack.benchmark.connection_hints)
                            if hints:
                                existing.connection_hints = hints
                                db.commit()
                                logger.info("  Backfilled connection_hints for '%s'", pack_info.filename)
                        except Exception:
                            pass  # non-critical backfill
                    logger.debug(
                        "  Pack '%s' unchanged (hash match) — skipping",
                        pack_info.filename,
                    )
                    stats["skipped"] += 1
                    continue
                else:
                    # Hash mismatch — upgrade
                    upgrade_pack(existing, pack_info.full_path, db, pack_hash=disk_hash)
                    db.commit()
                    stats["upgraded"] += 1
            else:
                # New pack — load fresh
                load_pack(pack_info.full_path, db, pack_hash=disk_hash)
                db.commit()
                stats["loaded"] += 1

        except Exception as exc:
            logger.error(
                "Failed to sync pack '%s': %s", pack_info.filename, exc, exc_info=True
            )
            db.rollback()
            stats["errors"] += 1

    logger.info(
        "Preloaded sync complete: %d loaded, %d upgraded, %d skipped, %d errors",
        stats["loaded"], stats["upgraded"], stats["skipped"], stats["errors"],
    )
    return stats
