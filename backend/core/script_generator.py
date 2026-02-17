"""Script Generation Engine — Phase 3 (Module 6).

Generates self-contained audit script packages for offline execution on
target machines.  Each package is a ZIP archive containing:

* The main audit script (Bash / PowerShell / SQL / command list)
* A rules_reference.json with the selected rules
* A README.txt with execution instructions
* An empty results/ directory placeholder
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.rule_tag import RuleTag
from backend.models.scan_preset import ScanPreset

logger = logging.getLogger("auditforge.core.script_generator")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Maps (platform_family, platform_hint) → (template_filename, script_ext)
PLATFORM_TEMPLATE_MAP: dict[str, tuple[str, str]] = {
    "linux": ("bash_audit.sh.j2", "run_audit.sh"),
    "windows": ("powershell_audit.ps1.j2", "run_audit.ps1"),
    "network": ("network_audit.txt.j2", "audit_commands.txt"),
}

DATABASE_TEMPLATE_MAP: dict[str, tuple[str, str]] = {
    "postgresql": ("postgresql_audit.sql.j2", "audit_queries.sql"),
    "oracle": ("oracle_audit.sql.j2", "audit_queries.sql"),
    "mssql": ("mssql_audit.sql.j2", "audit_queries.sql"),
    "sql server": ("mssql_audit.sql.j2", "audit_queries.sql"),
}

_jinja_env: Environment | None = None


def _get_jinja_env() -> Environment:
    """Lazily initialise and return the Jinja2 template environment."""
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape([]),
            keep_trailing_newline=True,
        )
    return _jinja_env


# ── Rule filtering ──────────────────────────────────────────


def filter_rules(
    db: Session,
    benchmark_id: int,
    *,
    selected_rule_ids: list[int] | None = None,
    category_filter: list[str] | None = None,
    severity_filter: list[str] | None = None,
    profile_filter: str | None = None,
    preset_id: int | None = None,
) -> list[Rule]:
    """Return rules matching the given filter criteria.

    Filter precedence:
    1. ``selected_rule_ids`` — explicit cherry-pick
    2. ``preset_id`` — loads saved selection criteria
    3. Any combination of category / severity / profile filters
    If no filters are supplied, all enabled rules with commands are returned.
    """

    query = (
        db.query(Rule)
        .filter(Rule.benchmark_id == benchmark_id, Rule.enabled.is_(True))
    )

    # 1. Explicit rule IDs take priority
    if selected_rule_ids:
        query = query.filter(Rule.id.in_(selected_rule_ids))
        return query.order_by(Rule.section_number).all()

    # 2. Preset – load its criteria
    if preset_id is not None:
        preset = db.query(ScanPreset).filter(ScanPreset.id == preset_id).first()
        if preset and preset.selection_criteria:
            try:
                criteria = json.loads(preset.selection_criteria)
            except (json.JSONDecodeError, TypeError):
                criteria = {}
            category_filter = criteria.get("category_filter") or category_filter
            severity_filter = criteria.get("severity_filter") or severity_filter
            profile_filter = criteria.get("profile_filter") or profile_filter

    # 3. Apply individual filters
    if category_filter:
        query = query.join(RuleTag).filter(RuleTag.tag_id.in_(category_filter))

    if severity_filter:
        query = query.filter(Rule.severity.in_(severity_filter))

    if profile_filter:
        query = query.filter(Rule.profile_applicability.ilike(f"%{profile_filter}%"))

    return query.order_by(Rule.section_number).all()


# ── Template selection ──────────────────────────────────────


def _resolve_template(benchmark: Benchmark) -> tuple[str, str]:
    """Choose the correct Jinja2 template and output filename for *benchmark*.

    Returns ``(template_filename, script_filename)``.
    """
    family = (benchmark.platform_family or "other").lower()

    if family == "database":
        platform_lower = (benchmark.platform or "").lower()
        for key, val in DATABASE_TEMPLATE_MAP.items():
            if key in platform_lower:
                return val
        # Fallback for unrecognised databases – use PostgreSQL style
        return DATABASE_TEMPLATE_MAP["postgresql"]

    if family in PLATFORM_TEMPLATE_MAP:
        return PLATFORM_TEMPLATE_MAP[family]

    # Fallback to generic text
    return ("generic_audit.txt.j2", "audit_commands.txt")


# ── Rule → template dict ───────────────────────────────────


def _rule_to_dict(rule: Rule) -> dict[str, Any]:
    """Serialize a Rule + its command into a plain dict for template rendering."""
    cmd = rule.commands
    return {
        "id": rule.id,
        "section_number": rule.section_number,
        "title": rule.title or "",
        "description": rule.description or "",
        "severity": rule.severity or "medium",
        "profile_applicability": rule.profile_applicability or "",
        "audit_command": cmd.audit_command if cmd else "",
        "expected_output_regex": cmd.expected_output_regex if cmd else "",
        "expected_output_description": cmd.expected_output_description if cmd else "",
        "remediation_command": cmd.remediation_command if cmd else "",
        "remediation_description": cmd.remediation_description if cmd else "",
    }


# ── Public API ──────────────────────────────────────────────


def preview_script_rules(
    db: Session,
    benchmark_id: int,
    **filter_kwargs: Any,
) -> list[dict[str, Any]]:
    """Return a lightweight list of rules that *would* be included in a script.

    Only rules that have a non-empty audit_command are kept.
    """

    rules = filter_rules(db, benchmark_id, **filter_kwargs)
    result: list[dict[str, Any]] = []
    for rule in rules:
        cmd = rule.commands
        if not cmd or not cmd.audit_command:
            continue
        result.append({
            "id": rule.id,
            "section_number": rule.section_number,
            "title": rule.title,
            "severity": rule.severity,
        })
    return result


def generate_script_package(
    db: Session,
    benchmark_id: int,
    scan_id: str | None = None,
    **filter_kwargs: Any,
) -> tuple[bytes, str]:
    """Generate a ZIP archive containing the audit script package.

    Returns ``(zip_bytes, zip_filename)``.
    """

    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise ValueError(f"Benchmark {benchmark_id} not found")

    rules = filter_rules(db, benchmark_id, **filter_kwargs)

    # Only include rules that have a non-empty audit command
    eligible_rules = [r for r in rules if r.commands and r.commands.audit_command]
    if not eligible_rules:
        raise ValueError("No eligible rules with audit commands found for the given filters")

    template_name, script_filename = _resolve_template(benchmark)
    env = _get_jinja_env()

    generation_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    effective_scan_id = scan_id or f"offline_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    rules_dicts = [_rule_to_dict(r) for r in eligible_rules]

    # Benchmark dict for templates
    benchmark_dict = {
        "name": benchmark.name,
        "version": benchmark.version,
        "platform": benchmark.platform,
        "platform_family": benchmark.platform_family,
    }

    context: dict[str, Any] = {
        "benchmark": benchmark_dict,
        "rules": rules_dicts,
        "generation_date": generation_date,
        "scan_id": effective_scan_id,
        "script_filename": script_filename,
    }

    # Render main script
    template = env.get_template(template_name)
    script_content = template.render(**context)

    # Render README
    readme_template = env.get_template("readme.txt.j2")
    readme_content = readme_template.render(**context)

    # Rules reference JSON
    rules_reference = json.dumps(rules_dicts, indent=2, default=str)

    # Build ZIP
    safe_name = benchmark.name.replace(" ", "_").replace("/", "_")
    safe_version = (benchmark.version or "unknown").replace(" ", "_")
    date_stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    folder_name = f"auditforge_audit_{safe_name}_{safe_version}_{date_stamp}"
    zip_filename = f"{folder_name}.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # PowerShell 5.1 needs a UTF-8 BOM to read non-ASCII correctly
        if script_filename.endswith(".ps1"):
            zf.writestr(
                f"{folder_name}/{script_filename}",
                "\ufeff" + script_content,
            )
        else:
            zf.writestr(f"{folder_name}/{script_filename}", script_content)
        zf.writestr(f"{folder_name}/rules_reference.json", rules_reference)
        zf.writestr(f"{folder_name}/README.txt", readme_content)
        # Create empty results directory placeholder
        zf.writestr(f"{folder_name}/results/.gitkeep", "")

    return buf.getvalue(), zip_filename
