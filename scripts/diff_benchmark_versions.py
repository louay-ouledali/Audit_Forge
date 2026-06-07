#!/usr/bin/env python3
"""Compare two .auditforge.json packs and report differences.

Usage
-----
    python scripts/diff_benchmark_versions.py v4.json v5.json
    python scripts/diff_benchmark_versions.py v4.json v5.json --json --output diff_report.json
    python scripts/diff_benchmark_versions.py v4.json v5.json --only-breaking

Reports:
  - New rules (added in B that are not in A)
  - Removed rules (present in A but not in B)
  - Modified rules (same section, different content)
  - Changed commands / expressions / FP conditions
  - Narrative group changes
  - Summary statistics
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.schemas.preloaded import PreloadedBenchmarkPack, validate_pack  # noqa: E402


#  Diff engine

# Fields that constitute a "breaking change" (affect scan/evaluation behaviour)
BREAKING_FIELDS = {
    "audit_command", "expected_output_expression", "remediation_command",
    "fp_conditions", "severity",
}

# Fields that are enrichment-only (affect reporting but not scanning)
ENRICHMENT_FIELDS = {
    "narrative_group", "risk_weight", "mitre_attack", "security_themes",
    "attack_chain_tags", "empty_output_interpretation", "output_value_map",
    "remediation_gpo_path", "remediation_risk", "safe_to_automate",
    "requires_restart", "related_rules", "group_with",
}

# Identity / documentation fields
DOC_FIELDS = {
    "title", "description", "rationale", "profile_applicability",
    "assessment_type", "default_value", "cis_controls", "enabled",
    "expected_output_description", "remediation_description", "tags",
}

ALL_TRACKED_FIELDS = BREAKING_FIELDS | ENRICHMENT_FIELDS | DOC_FIELDS


def _normalise_for_compare(val):
    """Normalise values so cosmetic differences don't trigger false diffs."""
    if val is None:
        return None
    if isinstance(val, list):
        # Sort lists of strings for stable comparison
        try:
            return sorted(val)
        except TypeError:
            return val
    if isinstance(val, dict):
        return {k: _normalise_for_compare(v) for k, v in sorted(val.items())}
    if isinstance(val, str):
        return val.strip()
    return val


def diff_rules(rule_a: dict, rule_b: dict) -> dict:
    """Compare two rule dicts and return field-level differences."""
    changes: dict[str, dict] = {}
    for field in ALL_TRACKED_FIELDS:
        val_a = _normalise_for_compare(rule_a.get(field))
        val_b = _normalise_for_compare(rule_b.get(field))
        if val_a != val_b:
            category = (
                "breaking" if field in BREAKING_FIELDS
                else "enrichment" if field in ENRICHMENT_FIELDS
                else "documentation"
            )
            changes[field] = {
                "old": rule_a.get(field),
                "new": rule_b.get(field),
                "category": category,
            }
    return changes


def diff_packs(pack_a: dict, pack_b: dict) -> dict:
    """Full diff between two pack dicts.

    Returns a structured report.
    """
    rules_a = {r["section_number"]: r for r in pack_a.get("rules", [])}
    rules_b = {r["section_number"]: r for r in pack_b.get("rules", [])}

    sections_a = set(rules_a.keys())
    sections_b = set(rules_b.keys())

    added_sections = sorted(sections_b - sections_a)
    removed_sections = sorted(sections_a - sections_b)
    common_sections = sorted(sections_a & sections_b)

    modified_rules: list[dict] = []
    breaking_count = 0
    enrichment_count = 0
    doc_count = 0

    for section in common_sections:
        changes = diff_rules(rules_a[section], rules_b[section])
        if changes:
            has_breaking = any(c["category"] == "breaking" for c in changes.values())
            has_enrichment = any(c["category"] == "enrichment" for c in changes.values())
            has_doc = any(c["category"] == "documentation" for c in changes.values())
            if has_breaking:
                breaking_count += 1
            if has_enrichment:
                enrichment_count += 1
            if has_doc:
                doc_count += 1

            modified_rules.append({
                "section_number": section,
                "title": rules_b[section].get("title", ""),
                "has_breaking_changes": has_breaking,
                "field_changes": changes,
            })

    # Narrative groups diff
    ng_a = set((pack_a.get("report_profile") or {}).get("narrative_groups", {}).keys())
    ng_b = set((pack_b.get("report_profile") or {}).get("narrative_groups", {}).keys())

    # Benchmark metadata diff
    bm_a = pack_a.get("benchmark", {})
    bm_b = pack_b.get("benchmark", {})

    return {
        "pack_a": {
            "name": bm_a.get("name", "?"),
            "version": bm_a.get("version", "?"),
            "total_rules": bm_a.get("total_rules", 0),
        },
        "pack_b": {
            "name": bm_b.get("name", "?"),
            "version": bm_b.get("version", "?"),
            "total_rules": bm_b.get("total_rules", 0),
        },
        "summary": {
            "rules_added": len(added_sections),
            "rules_removed": len(removed_sections),
            "rules_modified": len(modified_rules),
            "rules_unchanged": len(common_sections) - len(modified_rules),
            "with_breaking_changes": breaking_count,
            "with_enrichment_changes": enrichment_count,
            "with_doc_changes": doc_count,
            "narrative_groups_added": sorted(ng_b - ng_a),
            "narrative_groups_removed": sorted(ng_a - ng_b),
        },
        "added_rules": [
            {"section_number": s, "title": rules_b[s].get("title", "")}
            for s in added_sections
        ],
        "removed_rules": [
            {"section_number": s, "title": rules_a[s].get("title", "")}
            for s in removed_sections
        ],
        "modified_rules": modified_rules,
    }


#  Output formatting

def print_human_diff(report: dict, only_breaking: bool = False) -> None:
    """Pretty-print the diff report to stdout."""
    pa = report["pack_a"]
    pb = report["pack_b"]
    s = report["summary"]

    print("=" * 72)
    print("  AuditForge Pack Diff Report")
    print("=" * 72)
    print(f"\n  Pack A: {pa['name']} v{pa['version']}  ({pa['total_rules']} rules)")
    print(f"  Pack B: {pb['name']} v{pb['version']}  ({pb['total_rules']} rules)")

    print(f"\n  ┌──────────────────────────────────┬────────┐")
    print(f"  │ Metric                           │ Count  │")
    print(f"  ├──────────────────────────────────┼────────┤")
    print(f"  │ Rules added                      │ {s['rules_added']:>6} │")
    print(f"  │ Rules removed                    │ {s['rules_removed']:>6} │")
    print(f"  │ Rules modified                   │ {s['rules_modified']:>6} │")
    print(f"  │   ↳ with breaking changes        │ {s['with_breaking_changes']:>6} │")
    print(f"  │   ↳ with enrichment changes      │ {s['with_enrichment_changes']:>6} │")
    print(f"  │   ↳ with documentation changes   │ {s['with_doc_changes']:>6} │")
    print(f"  │ Rules unchanged                  │ {s['rules_unchanged']:>6} │")
    print(f"  └──────────────────────────────────┴────────┘")

    if s["narrative_groups_added"]:
        print(f"\n  New narrative groups: {', '.join(s['narrative_groups_added'])}")
    if s["narrative_groups_removed"]:
        print(f"  Removed narrative groups: {', '.join(s['narrative_groups_removed'])}")

    # Added rules
    if report["added_rules"] and not only_breaking:
        print(f"\n  ── Added Rules ({len(report['added_rules'])}) ──")
        for r in report["added_rules"]:
            print(f"    + [{r['section_number']}] {r['title']}")

    # Removed rules
    if report["removed_rules"]:
        print(f"\n  ── Removed Rules ({len(report['removed_rules'])}) ──")
        for r in report["removed_rules"]:
            print(f"    - [{r['section_number']}] {r['title']}")

    # Modified rules
    shown_modified = report["modified_rules"]
    if only_breaking:
        shown_modified = [m for m in shown_modified if m["has_breaking_changes"]]

    if shown_modified:
        label = "Breaking Changes" if only_breaking else "Modified Rules"
        print(f"\n  ── {label} ({len(shown_modified)}) ──")
        for m in shown_modified:
            marker = " ⚠ BREAKING" if m["has_breaking_changes"] else ""
            print(f"\n    [{m['section_number']}] {m['title']}{marker}")
            for field, change in m["field_changes"].items():
                if only_breaking and change["category"] != "breaking":
                    continue
                old_display = _truncate(str(change["old"]), 60)
                new_display = _truncate(str(change["new"]), 60)
                cat_icon = {"breaking": "🔴", "enrichment": "🟡", "documentation": "🔵"}
                icon = cat_icon.get(change["category"], "⚪")
                print(f"      {icon} {field}:")
                print(f"          old: {old_display}")
                print(f"          new: {new_display}")

    print(f"\n{'=' * 72}")


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else s[:max_len] + "..."


#  CLI

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two .auditforge.json benchmark packs."
    )
    parser.add_argument(
        "pack_a", type=str, help="Path to the old/base pack file",
    )
    parser.add_argument(
        "pack_b", type=str, help="Path to the new/updated pack file",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", default=False,
        help="Output machine-readable JSON",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Write output to file instead of stdout",
    )
    parser.add_argument(
        "--only-breaking", action="store_true", default=False,
        help="Only show breaking changes (audit_command, expression, severity, FP conditions)",
    )
    args = parser.parse_args()

    path_a = Path(args.pack_a)
    path_b = Path(args.pack_b)

    for p in (path_a, path_b):
        if not p.exists():
            print(f"[ERROR] File not found: {p}")
            sys.exit(1)

    try:
        data_a = json.loads(path_a.read_text(encoding="utf-8"))
        data_b = json.loads(path_b.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Invalid JSON: {exc}")
        sys.exit(1)

    report = diff_packs(data_a, data_b)

    if args.json_output:
        output_text = json.dumps(report, indent=2, ensure_ascii=False)
    else:
        # Capture the human-readable output
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            print_human_diff(report, only_breaking=args.only_breaking)
        output_text = f.getvalue()

    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"[SAVED] {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
