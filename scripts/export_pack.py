#!/usr/bin/env python3
"""Export a benchmark from the AuditForge database into a .auditforge.json pack.

Usage
-----
    python scripts/export_pack.py --benchmark-id 1 --output preloaded/windows_11_v5.json

The exported pack conforms to the PreloadedBenchmarkPack schema and can be fed
back into the enrichment pipeline or loaded at startup.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on sys.path so ``backend`` is importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal  # noqa: E402
from backend.models.benchmark import Benchmark  # noqa: E402
from backend.models.rule import Rule  # noqa: E402
from backend.schemas.preloaded import (  # noqa: E402
    CURRENT_SCHEMA_VERSION,
    PreloadedBenchmarkPack,
    validate_pack,
)


# helpers

def _safe_json_loads(value: str | None) -> list | dict | None:
    """Parse a JSON text column, returning *None* on failure / empty."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _build_rule_dict(rule: Rule) -> dict:
    """Map a SQLAlchemy Rule (+ its command & tags) to the pack rule dict."""
    cmd = rule.commands  # uselist=False → single object or None

    d: dict = {
        # Identity
        "section_number": rule.section_number,
        "title": rule.title,
        "description": rule.description,
        "rationale": rule.rationale,
        "profile_applicability": (
            _safe_json_loads(rule.profile_applicability)
            if isinstance(rule.profile_applicability, str) and rule.profile_applicability.startswith("[")
            else ([rule.profile_applicability] if rule.profile_applicability else None)
        ),
        "assessment_type": rule.assessment_type,
        "default_value": rule.default_value,
        "severity": rule.severity or "medium",
        "cis_controls": rule.cis_controls,
        "enabled": rule.enabled,
        "tags": [
            {"tag_id": t.tag_id, "source": t.source}
            for t in (rule.tags or [])
        ],

        # Semantic metadata (from pre-loaded fields)
        "narrative_group": rule.narrative_group,
        "security_themes": _safe_json_loads(rule.security_themes_json) or [],
        "attack_chain_tags": _safe_json_loads(rule.attack_chain_tags_json) or [],
        "mitre_attack": _safe_json_loads(rule.mitre_attack_json) or [],
        "risk_weight": rule.risk_weight or 5,
        "related_rules": _safe_json_loads(rule.related_rules_json) or [],
        "group_with": _safe_json_loads(rule.group_with_json) or [],
    }

    if cmd:
        d.update({
            # Audit command
            "audit_command": cmd.audit_command,
            "expected_output_expression": cmd.expected_output_regex,  # DB name differs
            "expected_output_description": cmd.expected_output_description,
            "remediation_command": cmd.remediation_command,
            "remediation_description": cmd.remediation_description,
            # Baked intelligence
            "empty_output_interpretation": cmd.empty_output_interpretation,
            "output_value_map": _safe_json_loads(cmd.output_value_map_json),
            "fp_conditions": _safe_json_loads(cmd.fp_conditions_json) or [],
            # Remediation metadata
            "remediation_gpo_path": cmd.remediation_gpo_path,
            "remediation_risk": cmd.remediation_risk,
            "safe_to_automate": cmd.safe_to_automate or False,
            "requires_restart": cmd.requires_restart or False,
        })
    else:
        d.update({
            "audit_command": None,
            "expected_output_expression": None,
            "expected_output_description": None,
            "remediation_command": None,
            "remediation_description": None,
            "empty_output_interpretation": None,
            "output_value_map": None,
            "fp_conditions": [],
            "remediation_gpo_path": None,
            "remediation_risk": None,
            "safe_to_automate": False,
            "requires_restart": False,
        })

    return d


# main

def export_benchmark(benchmark_id: int, output_path: Path, *, pretty: bool = True) -> None:
    """Export *benchmark_id* to a ``.auditforge.json`` file at *output_path*."""

    db = SessionLocal()
    try:
        benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
        if benchmark is None:
            print(f"[ERROR] Benchmark id={benchmark_id} not found.")
            sys.exit(1)

        rules = (
            db.query(Rule)
            .filter(Rule.benchmark_id == benchmark_id)
            .order_by(Rule.section_number)
            .all()
        )

        if not rules:
            print(f"[ERROR] Benchmark id={benchmark_id} has no rules.")
            sys.exit(1)

        print(f"Exporting benchmark: {benchmark.name} v{benchmark.version}")
        print(f"  Platform: {benchmark.platform} ({benchmark.platform_family})")
        print(f"  Rules:    {len(rules)}")

        # Build the report_profile skeleton — group rules by narrative_group
        narrative_keys: set[str] = set()
        for r in rules:
            if r.narrative_group:
                narrative_keys.add(r.narrative_group)

        narrative_groups: dict = {}
        for key in sorted(narrative_keys):
            narrative_groups[key] = {
                "display_name": key.replace("_", " ").title(),
                "narrative_template": "{{failed_count}} of {{total_count}} rules in this group failed.",
            }

        # If no narrative groups were set, create a default "uncategorised" group
        if not narrative_groups:
            narrative_groups["general"] = {
                "display_name": "General",
                "narrative_template": "{{failed_count}} of {{total_count}} rules failed.",
            }
            # Assign all rules to "general"
            for r in rules:
                r.narrative_group = "general"

        pack_dict = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "benchmark": {
                "name": benchmark.name,
                "version": benchmark.version,
                "platform": benchmark.platform,
                "platform_family": benchmark.platform_family,
                "cis_pdf_hash": (
                    f"sha256:{benchmark.pdf_hash}" if benchmark.pdf_hash else None
                ),
                "total_rules": len(rules),
                "release_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            },
            "report_profile": {
                "narrative_groups": narrative_groups,
            },
            "rules": [_build_rule_dict(r) for r in rules],
        }

        # Validate the pack before writing
        try:
            PreloadedBenchmarkPack.model_validate(pack_dict)
            print("  Schema:   VALID")
        except Exception as exc:
            print(f"  Schema:   INVALID — {exc}")
            print("[WARN] Writing file anyway (fix issues with enrich_benchmark.py)")

        # Write
        output_path.parent.mkdir(parents=True, exist_ok=True)
        indent = 2 if pretty else None
        output_path.write_text(
            json.dumps(pack_dict, indent=indent, ensure_ascii=False),
            encoding="utf-8",
        )
        size_kb = output_path.stat().st_size / 1024
        print(f"  Output:   {output_path}  ({size_kb:.1f} KB)")

    finally:
        db.close()


# CLI

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a benchmark from AuditForge DB to .auditforge.json pack format."
    )
    parser.add_argument(
        "--benchmark-id", "-b", type=int, default=None,
        help="Database ID of the benchmark to export",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output file path (e.g. preloaded/windows_11_v5.json)",
    )
    parser.add_argument(
        "--compact", action="store_true", default=False,
        help="Write compact (non-pretty) JSON",
    )
    parser.add_argument(
        "--list", "-l", dest="list_benchmarks", action="store_true", default=False,
        help="List all benchmarks in the database and exit",
    )
    args = parser.parse_args()

    if args.list_benchmarks:
        db = SessionLocal()
        try:
            benchmarks = db.query(Benchmark).order_by(Benchmark.id).all()
            if not benchmarks:
                print("No benchmarks found in the database.")
                return
            print(f"{'ID':>4}  {'Name':<55}  {'Version':<8}  {'Rules':>5}  {'Source':<15}  {'Ready'}")
            print("-" * 110)
            for b in benchmarks:
                rule_count = db.query(Rule).filter(Rule.benchmark_id == b.id).count()
                print(
                    f"{b.id:>4}  {b.name[:55]:<55}  {b.version:<8}  {rule_count:>5}  "
                    f"{b.source or 'user_imported':<15}  {b.is_ready}"
                )
        finally:
            db.close()
        return

    if not args.benchmark_id or not args.output:
        parser.error("--benchmark-id and --output are required when not using --list")

    export_benchmark(
        benchmark_id=args.benchmark_id,
        output_path=Path(args.output),
        pretty=not args.compact,
    )


if __name__ == "__main__":
    main()
