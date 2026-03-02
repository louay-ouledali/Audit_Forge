#!/usr/bin/env python3
"""Fix known data issues and export ALL benchmarks as preloaded .auditforge.json packs.

Fixes applied:
1. Strip leading 'v' from benchmark version strings (v5.0.0 → 5.0.0)
2. Add &&!=0 to 26 "but not 0" rules whose expression only has <= or <=
3. Fill 20 missing expected_output_regex values
4. Export all benchmarks to backend/preloaded/
5. Generate manifest.json

Usage (from project root, inside Docker):
    python scripts/fix_and_export_all.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand

PRELOADED_DIR = PROJECT_ROOT / "backend" / "preloaded"


# ═══════════════════════════════════════════════════════════════════════════════
#  Fix 1: Strip leading 'v' from version strings
# ═══════════════════════════════════════════════════════════════════════════════


def fix_version_strings(db) -> int:
    """Strip leading 'v' from benchmark.version (e.g. 'v5.0.0' → '5.0.0')."""
    count = 0
    for b in db.query(Benchmark).all():
        if b.version and b.version.startswith("v"):
            old = b.version
            b.version = b.version.lstrip("v")
            print(f"  [FIX v-prefix] B{b.id}: '{old}' → '{b.version}'")
            count += 1
    if count:
        db.commit()
    return count


# ═══════════════════════════════════════════════════════════════════════════════
#  Fix 2: Compound expressions for "but not 0" rules
# ═══════════════════════════════════════════════════════════════════════════════


def fix_but_not_zero(db) -> int:
    """Add &&!=0 to rules whose title says 'but not 0' but expression lacks it."""
    count = 0
    rules = db.query(Rule).filter(Rule.title.ilike("%but not 0%")).all()
    for r in rules:
        cmd = r.commands
        if not cmd or not cmd.expected_output_regex:
            continue
        expr = cmd.expected_output_regex.strip()
        # Only fix if it's a simple <=N or <=N expression without &&!=0
        if re.match(r"^<=\d+$", expr) or re.match(r"^>=\d+$", expr):
            new_expr = f"{expr}&&!=0"
            print(f"  [FIX !=0] B{r.benchmark_id} {r.section_number}: '{expr}' → '{new_expr}'")
            cmd.expected_output_regex = new_expr
            count += 1
    if count:
        db.commit()
    return count


# ═══════════════════════════════════════════════════════════════════════════════
#  Fix 3: Fill missing expected_output_regex
# ═══════════════════════════════════════════════════════════════════════════════

# Map of (benchmark_id, section_number) → correct expected expression
MISSING_EXPR_FIXES: dict[tuple[int, str], str] = {
    # Ubuntu 24.04 (B6)
    (6, "5.3.1.2"):  "not_empty",              # libpam-modules is installed (version exists)
    (6, "5.4.1.6"):  "==0",                    # All users' last pw change in past (0 violations)

    # RHEL 9 (B34)
    (34, "5.1.14"):  ">=1&&<=120",             # sshd LoginGraceTime 1-120 seconds

    # RHEL 10 (B33)
    (33, "1.7.4"):   "regex:^[0-6]44 0 0",    # /etc/motd perms: <=644 owned by root:root
    (33, "1.7.5"):   "regex:^[0-6]44 0 0",    # /etc/issue perms: <=644 owned by root:root
    (33, "5.1.13"):  ">=1&&<=120",             # sshd LoginGraceTime 1-120 seconds
    (33, "5.1.17"):  "regex:^10:30:60$",       # sshd MaxStartups 10:30:60

    # Apache Cassandra (B30)
    (30, "1.2"):     "not_empty",              # Java version installed
    (30, "1.3"):     "not_empty",              # Python version installed
    (30, "4.0.3"):   "not_empty",              # Cassandra version check

    # Apache HTTP Server 2.2 (B29)
    (29, "6.1"):     "contains:warn",          # LogLevel should be 'warn' or higher
    (29, "6.5"):     "not_empty",              # httpd version — patch level check

    # MongoDB 8 (B21)
    (21, "1.1"):     "not_empty",              # mongod version installed

    # NGINX (B36)
    (36, "1.1.1"):   "not_empty",              # nginx is installed (version exists)
    (36, "1.2.2"):   "not_empty",              # latest nginx package installed

    # PostgreSQL 16 (B17)
    (17, "3.1.8"):   "not_empty",              # log_rotation_age is set
    (17, "5.3"):     "not_empty",              # pg_hba.conf local auth configured
    (17, "5.4"):     "not_empty",              # pg_hba.conf host auth configured
    (17, "6.9"):     "contains:TLSv1.2",      # TLS min version >= 1.2

    # PostgreSQL 17 (B18)
    (18, "3.1.8"):   "not_empty",              # log_rotation_age is set
}


def fix_missing_expressions(db) -> int:
    """Fill in missing expected_output_regex values."""
    count = 0
    for (bid, sec), expected in MISSING_EXPR_FIXES.items():
        rule = db.query(Rule).filter(
            Rule.benchmark_id == bid,
            Rule.section_number == sec,
        ).first()
        if not rule:
            print(f"  [WARN] Rule B{bid} {sec} not found — skipping")
            continue
        cmd = rule.commands
        if not cmd:
            print(f"  [WARN] Rule B{bid} {sec} has no RuleCommand — skipping")
            continue
        old = cmd.expected_output_regex
        if old and old.strip():
            continue  # Already has a value — skip
        cmd.expected_output_regex = expected
        print(f"  [FIX expr] B{bid} {sec}: '' → '{expected}'")
        count += 1
    if count:
        db.commit()
    return count


# ═══════════════════════════════════════════════════════════════════════════════
#  Export all benchmarks to .auditforge.json packs
# ═══════════════════════════════════════════════════════════════════════════════


def _safe_json_loads(value: str | None) -> list | dict | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _slugify(name: str, version: str) -> str:
    """Generate a clean filename from benchmark name + version."""
    slug = name.lower()
    slug = re.sub(r"\bcis\b", "", slug)
    slug = re.sub(r"\bbenchmark\b", "", slug)
    slug = slug.strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    # Collapse multiple underscores
    slug = re.sub(r"_+", "_", slug)
    return f"{slug}_v{version}.auditforge.json"


def _build_rule_dict(rule: Rule) -> dict:
    """Map a SQLAlchemy Rule (+ command & tags) to pack rule dict."""
    cmd = rule.commands

    d: dict = {
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
        "enabled": rule.enabled if rule.enabled is not None else True,
        "tags": [
            {"tag_id": t.tag_id, "source": t.source}
            for t in (rule.tags or [])
        ],
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
            "audit_command": cmd.audit_command,
            "expected_output_expression": cmd.expected_output_regex,
            "expected_output_description": cmd.expected_output_description,
            "remediation_command": cmd.remediation_command,
            "remediation_description": cmd.remediation_description,
            "empty_output_interpretation": cmd.empty_output_interpretation,
            "output_value_map": _safe_json_loads(cmd.output_value_map_json),
            "fp_conditions": _safe_json_loads(cmd.fp_conditions_json) or [],
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


def export_benchmark(benchmark: Benchmark, rules: list[Rule], output_path: Path) -> str:
    """Export a benchmark to an .auditforge.json file. Returns SHA-256 hash."""

    # Build narrative groups from rule data
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

    if not narrative_groups:
        narrative_groups["general"] = {
            "display_name": "General",
            "narrative_template": "{{failed_count}} of {{total_count}} rules failed.",
        }
        for r in rules:
            if not r.narrative_group:
                r.narrative_group = "general"

    pack_dict = {
        "schema_version": "1.0",
        "benchmark": {
            "name": benchmark.name,
            "version": benchmark.version,
            "platform": benchmark.platform,
            "platform_family": benchmark.platform_family,
            "cis_pdf_hash": f"sha256:{benchmark.pdf_hash}" if benchmark.pdf_hash else None,
            "total_rules": len(rules),
            "release_date": None,
        },
        "report_profile": {
            "narrative_groups": narrative_groups,
        },
        "rules": [_build_rule_dict(r) for r in rules],
    }

    # Write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(pack_dict, indent=2, ensure_ascii=False)
    output_path.write_text(content, encoding="utf-8")

    # Compute hash
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return sha


def export_all(db) -> list[dict]:
    """Export all benchmarks. Returns list of manifest entries."""
    benchmarks = db.query(Benchmark).order_by(Benchmark.id).all()
    manifest_entries = []

    for b in benchmarks:
        rules = (
            db.query(Rule)
            .filter(Rule.benchmark_id == b.id)
            .order_by(Rule.section_number)
            .all()
        )
        if not rules:
            print(f"  [SKIP] B{b.id} {b.name} — no rules")
            continue

        filename = _slugify(b.name, b.version)
        output_path = PRELOADED_DIR / filename

        try:
            sha = export_benchmark(b, rules, output_path)
            size_kb = output_path.stat().st_size / 1024
            print(f"  [EXPORT] B{b.id} {b.name} v{b.version} → {filename} ({size_kb:.0f} KB, {len(rules)} rules)")

            manifest_entries.append({
                "filename": filename,
                "benchmark_name": b.name,
                "version": b.version,
                "platform_family": b.platform_family,
                "sha256": sha,
            })
        except Exception as exc:
            print(f"  [ERROR] B{b.id} {b.name}: {exc}")

    return manifest_entries


def write_manifest(entries: list[dict]) -> None:
    """Write the manifest.json file."""
    manifest = {
        "description": "AuditForge pre-loaded benchmark pack registry. Auto-synced at startup.",
        "packs": entries,
    }
    manifest_path = PRELOADED_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n  manifest.json written with {len(entries)} packs")


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    db = SessionLocal()

    try:
        print("=" * 70)
        print("AuditForge — Fix & Export All Benchmarks")
        print("=" * 70)

        # ── Phase 1: Fix data issues ─────────────────────────────────────
        print("\n1) Fixing version string v-prefix...")
        n = fix_version_strings(db)
        print(f"   Fixed {n} version strings\n")

        print("2) Fixing 'but not 0' compound expressions...")
        n = fix_but_not_zero(db)
        print(f"   Fixed {n} expressions\n")

        print("3) Fixing missing expected_output_regex...")
        n = fix_missing_expressions(db)
        print(f"   Fixed {n} expressions\n")

        # ── Phase 2: Export all benchmarks ───────────────────────────────
        print("4) Exporting all benchmarks to preloaded packs...")
        entries = export_all(db)
        print(f"\n   Exported {len(entries)} benchmarks")

        # ── Phase 3: Write manifest ──────────────────────────────────────
        print("\n5) Writing manifest.json...")
        write_manifest(entries)

        # ── Summary ──────────────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("DONE — All benchmarks exported to backend/preloaded/")
        print("On next startup, sync_preloaded() will load them into any fresh DB.")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    main()
