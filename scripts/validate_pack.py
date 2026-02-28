#!/usr/bin/env python3
"""Validate a .auditforge.json benchmark pack file.

Usage
-----
    python scripts/validate_pack.py preloaded/windows_11_v5.json
    python scripts/validate_pack.py preloaded/windows_11_v5.json --json
    python scripts/validate_pack.py preloaded/windows_11_v5.json --strict

Performs:
  1. JSON syntax check
  2. Pydantic schema validation (required fields, types, cross-references)
  3. Completeness report (% of rules with commands, FP conditions, etc.)
  4. Quality scoring
  5. Optional strict mode (warnings become errors)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.schemas.preloaded import (  # noqa: E402
    PackValidationResult,
    PreloadedBenchmarkPack,
    compute_pack_hash,
    validate_pack,
)


# ─── quality scoring ────────────────────────────────────────────────────────

QUALITY_WEIGHTS = {
    "commands": 25,
    "expressions": 20,
    "empty_interpretation": 15,
    "fp_conditions": 15,
    "narrative_groups": 10,
    "mitre_attack": 10,
    "remediation_commands": 5,
}

GRADE_THRESHOLDS = [
    (95, "A+"), (90, "A"), (85, "B+"), (80, "B"),
    (70, "C+"), (60, "C"), (50, "D"), (0, "F"),
]


def compute_quality_score(stats: dict) -> tuple[float, str]:
    """Return a weighted quality score 0-100 and a letter grade."""
    completeness = stats.get("completeness_pct", {})
    score = 0.0
    for key, weight in QUALITY_WEIGHTS.items():
        pct = completeness.get(key, 0)
        score += (pct / 100) * weight
    grade = "F"
    for threshold, letter in GRADE_THRESHOLDS:
        if score >= threshold:
            grade = letter
            break
    return round(score, 1), grade


# ─── detailed checks beyond schema ──────────────────────────────────────────

def run_deep_checks(pack: PreloadedBenchmarkPack) -> list[str]:
    """Return additional quality warnings not covered by Pydantic validators."""
    warnings: list[str] = []

    # Check group_with symmetry: if A group_with B, then B should group_with A
    section_groups: dict[str, set[str]] = {}
    for rule in pack.rules:
        section_groups[rule.section_number] = set(rule.group_with)

    for section, group in section_groups.items():
        for ref in group:
            if ref in section_groups and section not in section_groups[ref]:
                warnings.append(
                    f"Asymmetric group_with: {section} groups with {ref}, "
                    f"but {ref} does not group with {section}"
                )

    # Check for rules with commands but no expression
    for rule in pack.rules:
        if rule.audit_command and not rule.expected_output_expression:
            warnings.append(
                f"Rule {rule.section_number} has audit_command but no expected_output_expression"
            )

    # Check risk_weight distribution (too many at extreme values?)
    weights = [r.risk_weight for r in pack.rules]
    if weights:
        avg = sum(weights) / len(weights)
        if avg > 8:
            warnings.append(f"Average risk_weight is {avg:.1f} — most rules rated critical?")
        elif avg < 3:
            warnings.append(f"Average risk_weight is {avg:.1f} — most rules rated trivial?")

    # Check for very long audit commands (likely copy-paste issues)
    for rule in pack.rules:
        if rule.audit_command and len(rule.audit_command) > 2000:
            warnings.append(
                f"Rule {rule.section_number}: audit_command is {len(rule.audit_command)} chars "
                "(suspiciously long)"
            )

    # Check for empty FP condition explanations
    for rule in pack.rules:
        for fp in rule.fp_conditions:
            if len(fp.explanation) < 10:
                warnings.append(
                    f"Rule {rule.section_number}: FP condition '{fp.id}' has a very short explanation"
                )

    # Check that narrative groups are actually used
    used_groups = {r.narrative_group for r in pack.rules if r.narrative_group}
    defined_groups = set(pack.report_profile.narrative_groups.keys())
    unused = defined_groups - used_groups
    if unused:
        warnings.append(
            f"Narrative groups defined but never used: {', '.join(sorted(unused))}"
        )

    return warnings


# ─── output formatting ──────────────────────────────────────────────────────

def print_human_report(
    path: Path,
    pack: PreloadedBenchmarkPack | None,
    result: PackValidationResult,
    pack_hash: str,
    deep_warnings: list[str],
) -> None:
    """Pretty-print the validation report to stdout."""
    print("=" * 72)
    print(f"  AuditForge Pack Validation Report")
    print(f"  File: {path.name}")
    print("=" * 72)

    if not result.valid:
        print(f"\n  STATUS: INVALID\n")
        print("  Errors:")
        for e in result.errors:
            # Truncate very long Pydantic errors for readability
            display = e if len(e) < 300 else e[:300] + "..."
            print(f"    - {display}")
        print()
        return

    bm = pack.benchmark
    print(f"\n  Benchmark:  {bm.name}")
    print(f"  Version:    {bm.version}")
    print(f"  Platform:   {bm.platform} ({bm.platform_family})")
    print(f"  Rules:      {bm.total_rules}")
    print(f"  SHA-256:    {pack_hash[:16]}...")
    print(f"  Schema:     v{pack.schema_version}")

    # Completeness table
    stats = result.stats
    cpct = stats.get("completeness_pct", {})
    print(f"\n  {'Metric':<30} {'Count':>6}  {'Pct':>5}  {'Target':>6}")
    print("  " + "-" * 55)
    rows = [
        ("Audit commands", stats.get("with_audit_command", 0), cpct.get("commands", 0), "100%"),
        ("Expected expressions", stats.get("with_expression", 0), cpct.get("expressions", 0), "100%"),
        ("Empty output interp.", stats.get("with_empty_interpretation", 0), cpct.get("empty_interpretation", 0), ">=90%"),
        ("FP conditions", stats.get("with_fp_conditions", 0), cpct.get("fp_conditions", 0), ">=80%"),
        ("Narrative groups", stats.get("with_narrative_group", 0), cpct.get("narrative_groups", 0), "100%"),
        ("MITRE ATT&CK", stats.get("with_mitre_attack", 0), cpct.get("mitre_attack", 0), ">=70%"),
        ("Remediation commands", stats.get("with_remediation_command", 0), cpct.get("remediation_commands", 0), "100%"),
    ]
    total = stats.get("total_rules", 0)
    for label, count, pct, target in rows:
        bar = "#" * (pct // 5) + "." * (20 - pct // 5)
        print(f"  {label:<30} {count:>5}/{total:<5} {pct:>4}%  {target:>6}  {bar}")

    # Quality score
    score, grade = compute_quality_score(stats)
    print(f"\n  Quality Score: {score}/100  Grade: {grade}")

    # Narrative groups summary
    ng = pack.report_profile.narrative_groups
    print(f"\n  Narrative Groups ({len(ng)}):")
    for key, group in ng.items():
        count = sum(1 for r in pack.rules if r.narrative_group == key)
        print(f"    {key:<35} {group.display_name:<40} ({count} rules)")

    # Warnings
    all_warnings = result.warnings + deep_warnings
    if all_warnings:
        print(f"\n  Warnings ({len(all_warnings)}):")
        for i, w in enumerate(all_warnings, 1):
            print(f"    {i:>3}. {w}")

    print(f"\n  STATUS: VALID")
    print("=" * 72)


def output_json_report(
    path: Path,
    pack: PreloadedBenchmarkPack | None,
    result: PackValidationResult,
    pack_hash: str,
    deep_warnings: list[str],
) -> None:
    """Output machine-readable JSON report."""
    score, grade = compute_quality_score(result.stats) if result.valid else (0, "F")
    report = {
        "file": str(path),
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings + deep_warnings,
        "stats": result.stats,
        "quality_score": score,
        "quality_grade": grade,
        "pack_hash": pack_hash,
    }
    if pack:
        report["benchmark"] = {
            "name": pack.benchmark.name,
            "version": pack.benchmark.version,
            "platform": pack.benchmark.platform,
            "total_rules": pack.benchmark.total_rules,
        }
    # Use sys.stdout.buffer for safe UTF-8 output on Windows
    import sys as _sys
    _sys.stdout.buffer.write(
        json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    )


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a .auditforge.json benchmark pack file."
    )
    parser.add_argument(
        "pack_file", type=str,
        help="Path to the .auditforge.json file to validate",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", default=False,
        help="Output machine-readable JSON instead of human-readable report",
    )
    parser.add_argument(
        "--strict", action="store_true", default=False,
        help="Treat warnings as errors (exit with code 1 if any warnings)",
    )
    args = parser.parse_args()

    path = Path(args.pack_file)
    pack, result = validate_pack(path)

    pack_hash = ""
    if path.exists():
        pack_hash = compute_pack_hash(path)

    deep_warnings: list[str] = []
    if pack:
        deep_warnings = run_deep_checks(pack)

    if args.json_output:
        output_json_report(path, pack, result, pack_hash, deep_warnings)
    else:
        print_human_report(path, pack, result, pack_hash, deep_warnings)

    # Exit code
    if not result.valid:
        sys.exit(1)
    if args.strict and (result.warnings or deep_warnings):
        print(f"\n[STRICT] {len(result.warnings) + len(deep_warnings)} warnings treated as errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
