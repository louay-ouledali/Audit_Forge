#!/usr/bin/env python3
"""Interactive CLI for enriching rules in a .auditforge.json pack.

Usage
-----
    python scripts/enrich_benchmark.py --pack preloaded/windows_11_v5.json
    python scripts/enrich_benchmark.py --pack preloaded/windows_11_v5.json --filter missing-fp
    python scripts/enrich_benchmark.py --pack preloaded/windows_11_v5.json --auto-assign-groups
    python scripts/enrich_benchmark.py --pack preloaded/windows_11_v5.json --batch-mitre mapping.csv

Walks through each rule interactively, letting the operator add/edit:
  - False-positive conditions
  - Empty output interpretations
  - Output value maps
  - Narrative groups
  - MITRE ATT&CK mappings
  - Risk weights
  - Remediation metadata

Saves progress incrementally (can resume) and produces a delta report.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.schemas.preloaded import (  # noqa: E402
    PreloadedBenchmarkPack,
    validate_pack,
)


#  Helpers

def _load_pack(path: Path) -> tuple[dict, PreloadedBenchmarkPack]:
    """Load raw dict + validated pack from a JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    pack = PreloadedBenchmarkPack.model_validate(raw)
    return raw, pack


def _save_pack(path: Path, data: dict) -> None:
    """Write pack dict to disk (pretty-printed)."""
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _prompt(msg: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    result = input(f"  {msg}{suffix}: ").strip()
    return result if result else default


def _prompt_yes_no(msg: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    result = input(f"  {msg} ({hint}): ").strip().lower()
    if not result:
        return default
    return result in ("y", "yes")


def _print_rule_summary(rule: dict, i: int, total: int) -> None:
    """Print a concise rule summary for the interactive editor."""
    section = rule.get("section_number", "?")
    title = rule.get("title", "?")
    severity = rule.get("severity", "?")
    has_cmd = "✓" if rule.get("audit_command") else "✗"
    has_fp = "✓" if rule.get("fp_conditions") else "✗"
    has_interp = "✓" if rule.get("empty_output_interpretation") else "✗"
    has_narrative = "✓" if rule.get("narrative_group") else "✗"
    has_mitre = "✓" if rule.get("mitre_attack") else "✗"
    weight = rule.get("risk_weight", 5)

    print(f"\n{'─' * 72}")
    print(f"  Rule {i}/{total}: [{section}] {title}")
    print(f"  Severity: {severity}  |  Risk Weight: {weight}  |  Narrative: {rule.get('narrative_group', 'none')}")
    print(f"  Cmd:{has_cmd}  FP:{has_fp}  Interp:{has_interp}  Group:{has_narrative}  MITRE:{has_mitre}")
    if rule.get("audit_command"):
        cmd_preview = rule["audit_command"][:100]
        if len(rule["audit_command"]) > 100:
            cmd_preview += "..."
        print(f"  Command: {cmd_preview}")
    print(f"{'─' * 72}")


#  Filter modes

FILTERS = {
    "all":          lambda r: True,
    "missing-fp":   lambda r: not r.get("fp_conditions"),
    "missing-interp": lambda r: not r.get("empty_output_interpretation"),
    "missing-narrative": lambda r: not r.get("narrative_group"),
    "missing-mitre": lambda r: not r.get("mitre_attack"),
    "missing-remediation": lambda r: not r.get("remediation_command"),
    "high-risk":    lambda r: r.get("risk_weight", 5) >= 7,
    "no-command":   lambda r: not r.get("audit_command"),
}


#  Interactive editing

def edit_rule_interactive(rule: dict, narrative_keys: list[str]) -> dict:
    """Interactively edit enrichment fields on a single rule. Returns modified rule."""
    changes: list[str] = []

    # Narrative group
    current_ng = rule.get("narrative_group") or ""
    print(f"\n  Available narrative groups: {', '.join(narrative_keys)}")
    new_ng = _prompt("Narrative group", current_ng)
    if new_ng != current_ng:
        rule["narrative_group"] = new_ng if new_ng else None
        changes.append(f"narrative_group: '{current_ng}' → '{new_ng}'")

    # Risk weight
    current_rw = str(rule.get("risk_weight", 5))
    new_rw = _prompt("Risk weight (1-10)", current_rw)
    try:
        new_rw_int = int(new_rw)
        if 1 <= new_rw_int <= 10 and str(new_rw_int) != current_rw:
            rule["risk_weight"] = new_rw_int
            changes.append(f"risk_weight: {current_rw} → {new_rw_int}")
    except ValueError:
        pass

    # MITRE ATT&CK
    current_mitre = rule.get("mitre_attack") or []
    print(f"  Current MITRE: {current_mitre}")
    mitre_input = _prompt("MITRE ATT&CK (comma-separated, e.g. T1110.001,T1078)", ",".join(current_mitre))
    new_mitre = [t.strip() for t in mitre_input.split(",") if t.strip()] if mitre_input else []
    if new_mitre != current_mitre:
        rule["mitre_attack"] = new_mitre
        changes.append(f"mitre_attack: {current_mitre} → {new_mitre}")

    # Empty output interpretation
    current_interp = rule.get("empty_output_interpretation") or ""
    new_interp = _prompt("Empty output interpretation", current_interp)
    if new_interp != current_interp:
        rule["empty_output_interpretation"] = new_interp if new_interp else None
        changes.append("empty_output_interpretation updated")

    # Remediation risk
    current_risk = rule.get("remediation_risk") or ""
    new_risk = _prompt("Remediation risk (low/medium/high)", current_risk)
    if new_risk in ("low", "medium", "high") and new_risk != current_risk:
        rule["remediation_risk"] = new_risk
        changes.append(f"remediation_risk: '{current_risk}' → '{new_risk}'")

    # Safe to automate
    current_auto = rule.get("safe_to_automate", False)
    if _prompt_yes_no("Safe to automate?", current_auto) != current_auto:
        rule["safe_to_automate"] = not current_auto
        changes.append(f"safe_to_automate: {current_auto} → {not current_auto}")

    # Requires restart
    current_restart = rule.get("requires_restart", False)
    if _prompt_yes_no("Requires restart?", current_restart) != current_restart:
        rule["requires_restart"] = not current_restart
        changes.append(f"requires_restart: {current_restart} → {not current_restart}")

    # FP conditions
    if _prompt_yes_no("Add a false-positive condition?", False):
        fp: dict = {
            "id": _prompt("FP condition ID", "fp_" + rule.get("section_number", "").replace(".", "_")),
            "condition_type": _prompt("Type (output_pattern/context_check/value_range/service_absent/edition_mismatch)", "context_check"),
            "check": _prompt("Check expression"),
            "verdict": _prompt("Verdict (LIKELY_PASS/NOT_APPLICABLE/ACCEPTED_RISK/NEEDS_REVIEW)", "LIKELY_PASS"),
            "confidence": int(_prompt("Confidence (0-100)", "70")),
            "explanation": _prompt("Explanation"),
        }
        existing_fps = rule.get("fp_conditions") or []
        existing_fps.append(fp)
        rule["fp_conditions"] = existing_fps
        changes.append(f"Added FP condition: {fp['id']}")

    # Security themes
    current_themes = rule.get("security_themes") or []
    themes_input = _prompt("Security themes (comma-separated)", ",".join(current_themes))
    new_themes = [t.strip() for t in themes_input.split(",") if t.strip()] if themes_input else []
    if new_themes != current_themes:
        rule["security_themes"] = new_themes
        changes.append(f"security_themes updated ({len(new_themes)} themes)")

    if changes:
        print(f"  → {len(changes)} change(s) recorded for {rule.get('section_number')}")
    else:
        print(f"  → No changes for {rule.get('section_number')}")

    return rule


#  Batch operations

def auto_assign_narrative_groups(data: dict) -> int:
    """Heuristic assignment of narrative groups based on section prefix and title keywords.
    
    Returns number of rules updated.
    """
    # Common CIS Windows benchmark groupings
    PREFIX_MAP = {
        "1.1": "password_and_lockout",
        "1.2": "password_and_lockout",
        "2.2": "user_rights",
        "2.3": "security_options",
        "5.":  "system_services",
        "9.":  "firewall",
        "17.": "audit_logging",
        "18.": "administrative_templates",
        "19.": "administrative_templates",
    }
    KEYWORD_MAP = {
        "password": "password_and_lockout",
        "lockout": "password_and_lockout",
        "audit": "audit_logging",
        "log": "audit_logging",
        "firewall": "firewall",
        "defender": "windows_defender",
        "bitlocker": "encryption",
        "encrypt": "encryption",
        "remote desktop": "remote_access",
        "rdp": "remote_access",
        "winrm": "remote_access",
        "uac": "user_account_control",
    }

    count = 0
    groups_used: set[str] = set()
    for rule in data.get("rules", []):
        if rule.get("narrative_group"):
            groups_used.add(rule["narrative_group"])
            continue

        section = rule.get("section_number", "")
        title = (rule.get("title") or "").lower()

        assigned = None
        # Try prefix match first
        for prefix, group in PREFIX_MAP.items():
            if section.startswith(prefix):
                assigned = group
                break

        # Try keyword match on title
        if not assigned:
            for kw, group in KEYWORD_MAP.items():
                if kw in title:
                    assigned = group
                    break

        if not assigned:
            assigned = "general"

        rule["narrative_group"] = assigned
        groups_used.add(assigned)
        count += 1

    # Ensure narrative_groups are defined in report_profile
    rp = data.get("report_profile", {})
    ng = rp.get("narrative_groups", {})
    for group_key in groups_used:
        if group_key not in ng:
            ng[group_key] = {
                "display_name": group_key.replace("_", " ").title(),
                "narrative_template": "{{failed_count}} of {{total_count}} rules in this group failed.",
            }
    rp["narrative_groups"] = ng
    data["report_profile"] = rp

    return count


def batch_mitre_from_csv(data: dict, csv_path: Path) -> int:
    """Apply MITRE ATT&CK mappings from a CSV file.
    
    CSV format: section_number,technique_id[,technique_id...]
    Example:
        1.1.1,T1110.001,T1110.003
        1.1.2,T1110.001
    
    Returns number of rules updated.
    """
    mapping: dict[str, list[str]] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            section = row[0].strip()
            techniques = [t.strip() for t in row[1:] if t.strip()]
            if techniques:
                mapping[section] = techniques

    count = 0
    for rule in data.get("rules", []):
        section = rule.get("section_number", "")
        if section in mapping:
            rule["mitre_attack"] = mapping[section]
            count += 1

    return count


#  Delta report

def compute_delta(original: dict, modified: dict) -> dict:
    """Compare original and modified pack dicts, return a structured delta."""
    changes: list[dict] = []

    orig_rules = {r["section_number"]: r for r in original.get("rules", [])}
    mod_rules = {r["section_number"]: r for r in modified.get("rules", [])}

    # Fields we track for deltas
    TRACKED_FIELDS = [
        "narrative_group", "risk_weight", "mitre_attack", "security_themes",
        "attack_chain_tags", "empty_output_interpretation", "output_value_map",
        "fp_conditions", "remediation_risk", "safe_to_automate", "requires_restart",
        "remediation_gpo_path", "related_rules", "group_with",
    ]

    for section in mod_rules:
        if section not in orig_rules:
            continue
        orig_rule = orig_rules[section]
        mod_rule = mod_rules[section]
        rule_changes: dict[str, dict] = {}
        for field in TRACKED_FIELDS:
            old_val = orig_rule.get(field)
            new_val = mod_rule.get(field)
            if old_val != new_val:
                rule_changes[field] = {"old": old_val, "new": new_val}
        if rule_changes:
            changes.append({
                "section_number": section,
                "title": mod_rule.get("title", ""),
                "fields_changed": rule_changes,
            })

    # Report profile changes
    orig_ng = set((original.get("report_profile") or {}).get("narrative_groups", {}).keys())
    mod_ng = set((modified.get("report_profile") or {}).get("narrative_groups", {}).keys())
    new_groups = mod_ng - orig_ng
    removed_groups = orig_ng - mod_ng

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rules_modified": len(changes),
        "total_field_changes": sum(len(c["fields_changed"]) for c in changes),
        "narrative_groups_added": sorted(new_groups),
        "narrative_groups_removed": sorted(removed_groups),
        "rule_changes": changes,
    }


#  Main

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive CLI for enriching rules in a .auditforge.json pack."
    )
    parser.add_argument(
        "--pack", "-p", type=str, required=True,
        help="Path to the .auditforge.json pack file",
    )
    parser.add_argument(
        "--filter", "-f", type=str, default="all",
        choices=list(FILTERS.keys()),
        help="Filter which rules to show (default: all)",
    )
    parser.add_argument(
        "--auto-assign-groups", action="store_true", default=False,
        help="Automatically assign narrative_group based on section prefix and title keywords",
    )
    parser.add_argument(
        "--batch-mitre", type=str, default=None,
        help="CSV file with MITRE ATT&CK mappings (section_number,T1234,...)",
    )
    parser.add_argument(
        "--delta-output", type=str, default=None,
        help="Path to write the delta report JSON (default: <pack>_delta_<timestamp>.json)",
    )
    args = parser.parse_args()

    pack_path = Path(args.pack)
    if not pack_path.exists():
        print(f"[ERROR] File not found: {pack_path}")
        sys.exit(1)

    raw_data = json.loads(pack_path.read_text(encoding="utf-8"))
    original_data = deepcopy(raw_data)

    # Batch operations (non-interactive)
    if args.auto_assign_groups:
        count = auto_assign_narrative_groups(raw_data)
        print(f"[AUTO] Assigned narrative groups to {count} rules.")
        # Update total_rules in case auto-assign changed the set
        _save_pack(pack_path, raw_data)
        print(f"[SAVED] {pack_path}")

        # Write delta
        delta = compute_delta(original_data, raw_data)
        delta_path = args.delta_output or str(pack_path).replace(".json", "_delta_autogroup.json")
        Path(delta_path).write_text(json.dumps(delta, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[DELTA] {delta_path}  ({delta['rules_modified']} rules, {delta['total_field_changes']} field changes)")
        return

    if args.batch_mitre:
        csv_path = Path(args.batch_mitre)
        if not csv_path.exists():
            print(f"[ERROR] CSV file not found: {csv_path}")
            sys.exit(1)
        count = batch_mitre_from_csv(raw_data, csv_path)
        print(f"[BATCH] Applied MITRE mappings to {count} rules from {csv_path.name}")
        _save_pack(pack_path, raw_data)
        print(f"[SAVED] {pack_path}")

        delta = compute_delta(original_data, raw_data)
        delta_path = args.delta_output or str(pack_path).replace(".json", "_delta_mitre.json")
        Path(delta_path).write_text(json.dumps(delta, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[DELTA] {delta_path}  ({delta['rules_modified']} rules, {delta['total_field_changes']} field changes)")
        return

    # Interactive enrichment
    rules = raw_data.get("rules", [])
    rule_filter = FILTERS.get(args.filter, FILTERS["all"])
    filtered_indices = [i for i, r in enumerate(rules) if rule_filter(r)]

    if not filtered_indices:
        print(f"[INFO] No rules match filter '{args.filter}'. Nothing to enrich.")
        return

    narrative_keys = list(
        (raw_data.get("report_profile") or {}).get("narrative_groups", {}).keys()
    )

    print(f"\nEnriching {len(filtered_indices)} of {len(rules)} rules (filter: {args.filter})")
    print("Commands: [Enter] to accept defaults, [s] to skip, [q] to save & quit\n")

    modified_count = 0
    for idx_num, rule_idx in enumerate(filtered_indices, 1):
        rule = rules[rule_idx]
        _print_rule_summary(rule, idx_num, len(filtered_indices))

        action = input("  [Enter=edit, s=skip, q=quit]: ").strip().lower()
        if action == "q":
            break
        if action == "s":
            continue

        original_rule = deepcopy(rule)
        rules[rule_idx] = edit_rule_interactive(rule, narrative_keys)
        if rules[rule_idx] != original_rule:
            modified_count += 1

        # Save incrementally every 5 rules
        if modified_count > 0 and modified_count % 5 == 0:
            _save_pack(pack_path, raw_data)
            print(f"  [AUTO-SAVE] Progress saved ({modified_count} rules modified)")

    # Final save
    if modified_count > 0:
        _save_pack(pack_path, raw_data)
        print(f"\n[SAVED] {pack_path}  ({modified_count} rules modified)")

        # Delta report
        delta = compute_delta(original_data, raw_data)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        delta_path = args.delta_output or str(pack_path).replace(".json", f"_delta_{timestamp}.json")
        Path(delta_path).write_text(json.dumps(delta, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[DELTA] {delta_path}")
        print(f"  Rules modified: {delta['rules_modified']}")
        print(f"  Field changes:  {delta['total_field_changes']}")
        if delta["narrative_groups_added"]:
            print(f"  New groups:     {', '.join(delta['narrative_groups_added'])}")
    else:
        print("\n[INFO] No changes made.")


if __name__ == "__main__":
    main()
