"""Core report generation logic - data aggregation and export to PDF, Excel, CSV, HTML."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

import json

from jinja2 import Environment, FileSystemLoader
import re as _re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, joinedload

# Regex matching characters illegal in Excel/openpyxl cells (ASCII control chars except tab/newline/CR)
_ILLEGAL_XLSX_RE = _re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')

from backend.ai.llm_manager import llm_manager
from backend.core.false_positive_detector import enrich_findings_with_fp
from backend.core.text_utils import normalize_unicode
from backend.models.benchmark import Benchmark
from backend.models.client import Client
from backend.models.finding import Finding
from backend.models.mission import Mission
from backend.models.rule import Rule
from backend.models.scan import Scan
from backend.models.target import Target

logger = logging.getLogger("auditforge.reports")

TEMPLATES_DIR = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "templates")

# Excel color fills
FILL_CRITICAL = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
FILL_HIGH = PatternFill(start_color="FF8C00", end_color="FF8C00", fill_type="solid")
FILL_MEDIUM = PatternFill(start_color="FFD700", end_color="FFD700", fill_type="solid")
FILL_LOW = PatternFill(start_color="4169E1", end_color="4169E1", fill_type="solid")
FILL_INFORMATIONAL = PatternFill(start_color="9CA3AF", end_color="9CA3AF", fill_type="solid")
FILL_PASS = PatternFill(start_color="90EE90", end_color="90EE90", fill_type="solid")
FILL_FAIL = PatternFill(start_color="FFB6C1", end_color="FFB6C1", fill_type="solid")

SEVERITY_FILLS = {
    "critical": FILL_CRITICAL,
    "high": FILL_HIGH,
    "medium": FILL_MEDIUM,
    "low": FILL_LOW,
    "informational": FILL_INFORMATIONAL,
}


# ---------------------------------------------------------------------------
# Data aggregation
# ---------------------------------------------------------------------------

def aggregate_report_data(
    scope: str,
    scope_id: int | None,
    scan_ids: list[int] | None,
    db: Session,
    excluded_rule_ids: list[int] | None = None,
) -> dict:
    """Query the database and return a normalised report data dict."""
    scans: list[Scan] = []
    _excluded = set(excluded_rule_ids) if excluded_rule_ids else set()

    if scope == "scan":
        scan = (
            db.query(Scan)
            .options(joinedload(Scan.target).joinedload(Target.client))
            .filter(Scan.id == scope_id)
            .first()
        )
        if scan:
            scans = [scan]

    elif scope == "target":
        target = (
            db.query(Target)
            .options(joinedload(Target.client))
            .filter(Target.id == scope_id)
            .first()
        )
        if target:
            scans = db.query(Scan).filter(Scan.target_id == target.id).all()

    elif scope == "mission":
        mission = (
            db.query(Mission)
            .options(joinedload(Mission.client))
            .filter(Mission.id == scope_id)
            .first()
        )
        if mission:
            # Scans now have direct mission_id
            scans = db.query(Scan).filter(Scan.mission_id == mission.id).all()

    elif scope == "custom":
        if scan_ids:
            scans = (
                db.query(Scan)
                .options(joinedload(Scan.target).joinedload(Target.client))
                .filter(Scan.id.in_(scan_ids))
                .all()
            )

    # Determine client / mission context from the first available scan
    client_name = ""
    mission_name = ""
    if scans:
        first_scan = scans[0]
        # Try mission from scan first (direct link)
        if first_scan.mission_id:
            mission_obj = db.query(Mission).filter(Mission.id == first_scan.mission_id).first()
            if mission_obj:
                mission_name = mission_obj.name or ""
                client_obj = db.query(Client).filter(Client.id == mission_obj.client_id).first()
                if client_obj:
                    client_name = client_obj.name or ""
        # Fallback: get client from target
        if not client_name:
            target_obj = db.query(Target).filter(Target.id == first_scan.target_id).first()
            if target_obj:
                client_obj = db.query(Client).filter(Client.id == target_obj.client_id).first()
                if client_obj:
                    client_name = client_obj.name or ""

    # Build per-target structure (batch-loaded)
    targets_map: dict[int, dict] = {}
    # Pre-load all targets and benchmarks for scans
    _target_ids = {s.target_id for s in scans}
    _targets_bulk = {t.id: t for t in db.query(Target).filter(Target.id.in_(_target_ids)).all()} if _target_ids else {}
    _bench_ids = {s.benchmark_id for s in scans if s.benchmark_id}
    _bench_bulk = {b.id: b for b in db.query(Benchmark).filter(Benchmark.id.in_(_bench_ids)).all()} if _bench_ids else {}

    for scan in scans:
        target_obj = _targets_bulk.get(scan.target_id)
        if not target_obj:
            continue
        if target_obj.id not in targets_map:
            targets_map[target_obj.id] = {
                "hostname": target_obj.hostname or "",
                "ip_address": target_obj.ip_address or "",
                "target_type": target_obj.target_type or "",
                "os_details": target_obj.os_details or "",
                "scans": [],
            }
        benchmark = _bench_bulk.get(scan.benchmark_id)
        targets_map[target_obj.id]["scans"].append({
            "id": scan.id,
            "benchmark_name": benchmark.name if benchmark else "",
            "scan_mode": scan.scan_mode or "",
            "compliance_percentage": scan.compliance_percentage,
            "passed": scan.passed or 0,
            "failed": scan.failed or 0,
            "errors": scan.errors or 0,
            "completed_at": str(scan.completed_at) if scan.completed_at else "",
        })

    # Collect findings
    scan_id_list = [s.id for s in scans]
    findings_rows: list[dict] = []
    total_passed = 0
    total_failed = 0
    total_errors = 0
    total_rules = 0
    severity_stats: dict[str, dict[str, int]] = {}

    if scan_id_list:
        db_findings = (
            db.query(Finding)
            .filter(Finding.scan_id.in_(scan_id_list))
            .all()
        )

        # ── Batch-load related entities to avoid N+1 queries ──
        rule_ids = {f.rule_id for f in db_findings if f.rule_id}
        rules_map: dict[int, Rule] = {}
        if rule_ids:
            for r in db.query(Rule).filter(Rule.id.in_(rule_ids)).all():
                rules_map[r.id] = r

        scans_map: dict[int, Scan] = {s.id: s for s in scans}
        target_ids = {s.target_id for s in scans if s.target_id}
        targets_lookup: dict[int, Target] = {}
        if target_ids:
            for t in db.query(Target).filter(Target.id.in_(target_ids)).all():
                targets_lookup[t.id] = t

        benchmark_ids = {s.benchmark_id for s in scans if s.benchmark_id}
        benchmarks_lookup: dict[int, Benchmark] = {}
        if benchmark_ids:
            for b in db.query(Benchmark).filter(Benchmark.id.in_(benchmark_ids)).all():
                benchmarks_lookup[b.id] = b

        for f in db_findings:
            # Skip excluded rules
            if _excluded and f.rule_id in _excluded:
                continue
            rule = rules_map.get(f.rule_id)
            scan_obj = scans_map.get(f.scan_id)
            target_obj = targets_lookup.get(scan_obj.target_id) if scan_obj else None
            benchmark = benchmarks_lookup.get(scan_obj.benchmark_id) if scan_obj else None

            sev = (f.severity or (rule.severity if rule else "medium") or "medium").lower()
            status = (f.status or "").upper()

            findings_rows.append({
                "_rule_id": f.rule_id,
                "scan_id": f.scan_id,
                "target_hostname": target_obj.hostname if target_obj else "",
                "benchmark_name": benchmark.name if benchmark else "",
                "section_number": rule.section_number if rule else "",
                "rule_title": normalize_unicode(rule.title) if rule else "",
                "description": normalize_unicode(rule.description) if rule else "",
                "rationale": normalize_unicode(rule.rationale) if rule else "",
                "default_value": normalize_unicode(rule.default_value) if rule else "",
                "severity": sev,
                "status": status,
                "actual_output": normalize_unicode(f.actual_output or ""),
                "expected_output": normalize_unicode(f.expected_output or ""),
                "remediation": normalize_unicode(rule.remediation_description_raw) if rule else "",
                "evaluation_explanation": normalize_unicode(f.evaluation_explanation or ""),
                "ai_advice": normalize_unicode(f.ai_advice or ""),
                "auditor_notes": normalize_unicode(f.auditor_notes or ""),
                "auditor_override": normalize_unicode(f.auditor_override or ""),
            })

            total_rules += 1
            if status == "PASS":
                total_passed += 1
            elif status == "FAIL":
                total_failed += 1
            elif status == "ERROR":
                total_errors += 1

            if sev not in severity_stats:
                severity_stats[sev] = {"total": 0, "passed": 0, "failed": 0}
            severity_stats[sev]["total"] += 1
            if status == "PASS":
                severity_stats[sev]["passed"] += 1
            elif status == "FAIL":
                severity_stats[sev]["failed"] += 1

    overall_compliance = round((total_passed / total_rules) * 100, 1) if total_rules > 0 else 0.0

    # Date range
    completed_dates = [s.completed_at for s in scans if s.completed_at]
    if completed_dates:
        earliest = min(completed_dates)
        latest = max(completed_dates)
        date_range = f"{earliest.strftime('%Y-%m-%d')} to {latest.strftime('%Y-%m-%d')}"
    else:
        date_range = "N/A"

    # Per-target compliance summary
    by_target: list[dict] = []
    for _tid, tdata in targets_map.items():
        t_p = sum(s["passed"] for s in tdata["scans"])
        t_f = sum(s["failed"] for s in tdata["scans"])
        t_e = sum(s["errors"] for s in tdata["scans"])
        t_total = t_p + t_f + t_e
        by_target.append({
            "hostname": tdata["hostname"],
            "ip_address": tdata["ip_address"],
            "compliance": round((t_p / t_total) * 100, 1) if t_total > 0 else 0,
            "passed": t_p, "failed": t_f, "errors": t_e, "total": t_total,
        })

    # Category-level stats (group by 1st section number)
    by_category: dict[str, dict] = {}
    for f in findings_rows:
        sec = f.get("section_number", "")
        cat = sec.split(".")[0] if sec else "Other"
        if cat not in by_category:
            by_category[cat] = {"total": 0, "passed": 0, "failed": 0, "label": f"Section {cat}"}
        by_category[cat]["total"] += 1
        if f["status"] == "PASS":
            by_category[cat]["passed"] += 1
        elif f["status"] == "FAIL":
            by_category[cat]["failed"] += 1

    # ── False-positive detection ──
    findings_rows, fp_summary = enrich_findings_with_fp(findings_rows)

    return {
        "title": "",
        "client_name": client_name,
        "mission_name": mission_name,
        "date_range": date_range,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "targets": list(targets_map.values()),
        "findings": findings_rows,
        "summary": {
            "total_rules": total_rules,
            "passed": total_passed,
            "failed": total_failed,
            "errors": total_errors,
            "overall_compliance": overall_compliance,
            "by_severity": severity_stats,
        },
        "scans": [
            {
                "id": s.id,
                "target_id": s.target_id,
                "benchmark_id": s.benchmark_id,
                "status": s.status,
                "compliance_percentage": s.compliance_percentage,
                "completed_at": str(s.completed_at) if s.completed_at else "",
            }
            for s in scans
        ],
        "by_target": by_target,
        "by_category": by_category,
        "fp_summary": fp_summary,
        "ai_summary": None,
    }


# ---------------------------------------------------------------------------
# Helper: build grouped findings for report builder
# ---------------------------------------------------------------------------

_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}


def _enrich_group(name: str, finds: list[dict], summary_text: str) -> dict:
    """Build a fully-enriched group dict with severity breakdown, compliance, sorted findings."""
    # Sort findings: severity order (critical→low), then FAIL before PASS
    finds_sorted = sorted(
        finds,
        key=lambda f: (_SEV_ORDER.get(f.get("severity", "medium"), 5), 0 if f.get("status") == "FAIL" else 1),
    )

    pass_count = sum(1 for f in finds if f.get("status") == "PASS")
    fail_count = sum(1 for f in finds if f.get("status") == "FAIL")
    error_count = sum(1 for f in finds if f.get("status") == "ERROR")
    total = len(finds)
    compliance_pct = round((pass_count / total) * 100, 1) if total > 0 else 0.0

    # Severity breakdown (failed only — for risk heatmap)
    sev_counts: dict[str, int] = {}
    sev_detail: dict[str, dict[str, int]] = {}
    for sev in ("critical", "high", "medium", "low", "informational"):
        s_total = sum(1 for f in finds if f.get("severity") == sev)
        s_pass = sum(1 for f in finds if f.get("severity") == sev and f.get("status") == "PASS")
        s_fail = sum(1 for f in finds if f.get("severity") == sev and f.get("status") == "FAIL")
        sev_counts[sev] = s_fail  # used in heatmap (failed count)
        if s_total > 0:
            sev_detail[sev] = {"total": s_total, "passed": s_pass, "failed": s_fail}

    return {
        "name": name,
        "findings": finds_sorted,
        "summary": summary_text,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "total_count": total,
        "compliance_pct": compliance_pct,
        "sev_counts": sev_counts,
        "sev_detail": sev_detail,
    }


def _build_grouped_findings(data: dict, findings: list[dict]) -> list[dict] | None:
    """Build grouped findings from builder_groups in data.

    Returns a list of enriched group dicts or None if no builder groups are set.
    Each group contains: name, findings (sorted by severity), summary, pass/fail/error counts,
    compliance_pct, sev_counts (failed by severity), sev_detail (per-severity breakdown).
    """
    builder_groups = data.get("builder_groups")
    if not builder_groups:
        return None

    group_summaries = data.get("group_summaries") or {}

    grouped = []
    for bg in builder_groups:
        rule_id_set = set(bg["rule_ids"])
        group_finds = [f for f in findings if f.get("_rule_id") in rule_id_set]
        grouped.append(_enrich_group(bg["name"], group_finds, group_summaries.get(bg["name"], "")))

    # Add ungrouped findings
    grouped_ids = set()
    for bg in builder_groups:
        grouped_ids.update(bg["rule_ids"])
    ungrouped = [f for f in findings if f.get("_rule_id") not in grouped_ids]
    if ungrouped:
        grouped.append(_enrich_group("Other", ungrouped, group_summaries.get("Other", "")))

    return grouped


# ---------------------------------------------------------------------------
# Shared chart generation (used by both PDF and HTML)
# ---------------------------------------------------------------------------

def _generate_all_charts(data: dict, grouped_findings: list[dict] | None) -> dict:
    """Generate all SVG charts and return as a dict of chart_name → SVG string.

    This avoids duplicating chart generation logic between PDF and HTML exporters.
    """
    from backend.core.chart_helpers import (
        generate_donut_svg,
        generate_hbar_svg,
        generate_risk_heatmap_svg,
        generate_mini_donut_svg,
        generate_stacked_hbar_svg,
        generate_fp_gauge_svg,
        generate_treemap_svg,
        generate_radar_svg,
        generate_waterfall_svg,
    )

    summary = data["summary"]
    charts: dict[str, str] = {}

    # 1. Donut: results distribution
    charts["chart_donut"] = generate_donut_svg([
        {"label": "Passed", "value": summary["passed"], "color": "#22c55e"},
        {"label": "Failed", "value": summary["failed"], "color": "#ef4444"},
        {"label": "Errors", "value": summary["errors"], "color": "#8b5cf6"},
    ], title="Results Distribution")

    # 2. Severity compliance bars
    sev_items = []
    for sev in ("critical", "high", "medium", "low", "informational"):
        info = summary["by_severity"].get(sev, {"total": 0, "passed": 0})
        comp = round((info["passed"] / info["total"]) * 100, 1) if info["total"] > 0 else 0
        colors = {"critical": "#dc2626", "high": "#ea580c", "medium": "#d97706", "low": "#2563eb", "informational": "#6b7280"}
        sev_items.append({"label": sev.capitalize(), "value": comp, "color": colors[sev]})
    charts["chart_severity"] = generate_hbar_svg(sev_items, title="Compliance by Severity")

    # 3. Per-target compliance bars
    target_items = []
    for t in data.get("by_target", []):
        c = t["compliance"]
        color = "#22c55e" if c >= 80 else "#f59e0b" if c >= 50 else "#ef4444"
        target_items.append({"label": t["hostname"] or t["ip_address"], "value": c, "color": color})
    charts["chart_targets"] = generate_hbar_svg(target_items, title="Compliance by Target") if len(target_items) > 1 else ""

    # 4. Category stacked bar
    by_cat = data.get("by_category", {})
    cat_items = [
        {"label": info.get("label", f"Section {k}"), "passed": info.get("passed", 0), "failed": info.get("failed", 0)}
        for k, info in sorted(by_cat.items(), key=lambda x: (not x[0].isdigit(), x[0]))
    ]
    charts["chart_categories"] = generate_stacked_hbar_svg(cat_items, title="Findings by Category") if cat_items else ""

    # 5. Grouped charts & risk heatmap
    charts["chart_risk_heatmap"] = ""
    charts["chart_group_compliance"] = ""
    if grouped_findings:
        hm_groups = [{"name": g["name"], "sev_counts": g["sev_counts"]} for g in grouped_findings]
        charts["chart_risk_heatmap"] = generate_risk_heatmap_svg(hm_groups)

        gc_items = [
            {"label": g["name"], "passed": g["pass_count"], "failed": g["fail_count"]}
            for g in grouped_findings
        ]
        charts["chart_group_compliance"] = generate_stacked_hbar_svg(gc_items, title="Compliance by Group")

        for g in grouped_findings:
            g["mini_donut"] = generate_mini_donut_svg(g["pass_count"], g["fail_count"], g["error_count"])

    # 6. False-positive gauge
    fp_summary = data.get("fp_summary", {})
    charts["chart_fp_gauge"] = ""
    if fp_summary.get("total_suspects", 0) > 0:
        charts["chart_fp_gauge"] = generate_fp_gauge_svg(
            fp_summary.get("high_confidence", 0),
            fp_summary.get("medium_confidence", 0),
            fp_summary.get("low_confidence", 0),
            summary["failed"],
        )

    # 7. Category treemap
    cat_treemap_items = [
        {"label": info.get("label", f"Section {k}"), "total": info["total"], "passed": info["passed"], "failed": info["failed"]}
        for k, info in sorted(by_cat.items(), key=lambda x: (not x[0].isdigit(), x[0]))
    ]
    charts["chart_treemap"] = generate_treemap_svg(cat_treemap_items, title="Category Compliance Map") if cat_treemap_items else ""

    # 8. Compliance radar
    radar_cats = [
        {"label": info.get("label", f"Section {k}"),
         "compliance": round((info["passed"] / info["total"]) * 100, 1) if info["total"] > 0 else 0}
        for k, info in sorted(by_cat.items(), key=lambda x: (not x[0].isdigit(), x[0]))
    ]
    charts["chart_radar"] = generate_radar_svg(radar_cats, title="Compliance by Category") if len(radar_cats) >= 3 else ""

    # 9. Compliance waterfall
    charts["chart_waterfall"] = generate_waterfall_svg(
        cat_treemap_items, summary["total_rules"], summary["passed"],
        title="Compliance Waterfall - Failures by Category",
    ) if cat_treemap_items else ""

    return charts


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def generate_pdf_report(data: dict, include_passed: bool, db: Session) -> bytes:
    """Render an HTML template with Jinja2 and convert to PDF via WeasyPrint."""
    from weasyprint import HTML  # imported here to isolate heavy dep

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("report.html.j2")

    if not include_passed:
        data = {**data, "findings": [f for f in data["findings"] if f["status"] != "PASS"]}

    # Phase 2: grouped findings & builder metadata for template
    grouped_findings = _build_grouped_findings(data, data["findings"])
    data["grouped_findings"] = grouped_findings
    data["section_toggles"] = data.get("sections") or {}
    data["group_summaries"] = data.get("group_summaries") or {}
    data["audience"] = data.get("audience", "technical")
    data["has_builder"] = bool(data.get("builder_groups"))

    # Generate all SVG charts (shared logic)
    charts = _generate_all_charts(data, grouped_findings)
    data.update(charts)
    data["fp_summary"] = data.get("fp_summary", {})

    html_string = template.render(**data, include_passed=include_passed)

    try:
        pdf_bytes = HTML(string=html_string).write_pdf()
    except Exception as exc:
        logger.exception("WeasyPrint PDF generation failed")
        raise RuntimeError(f"PDF generation failed: {exc}") from exc

    return pdf_bytes


# ---------------------------------------------------------------------------
# Excel generation
# ---------------------------------------------------------------------------

def generate_excel_report(data: dict, include_passed: bool) -> bytes:
    """Create a multi-sheet Excel workbook and return as bytes."""
    wb = Workbook()

    # ── Sheet 1: Executive Summary ──
    ws1 = wb.active
    ws1.title = "Executive Summary"
    summary = data["summary"]
    header_font = Font(bold=True, size=14)
    label_font = Font(bold=True)

    ws1.append(["Audit Report - Executive Summary"])
    ws1["A1"].font = header_font
    ws1.append([])
    ws1.append(["Client", data.get("client_name", "")])
    ws1.append(["Mission", data.get("mission_name", "")])
    ws1.append(["Date Range", data.get("date_range", "")])
    ws1.append(["Generated", data.get("generated_at", "")])
    ws1.append([])
    ws1.append(["Metric", "Value"])
    ws1["A8"].font = label_font
    ws1["B8"].font = label_font
    ws1.append(["Overall Compliance", f"{summary['overall_compliance']}%"])
    ws1.append(["Total Rules", summary["total_rules"]])
    ws1.append(["Passed", summary["passed"]])
    ws1.append(["Failed", summary["failed"]])
    ws1.append(["Errors", summary["errors"]])
    ws1.append([])
    ws1.append(["Severity", "Total", "Passed", "Failed"])
    ws1["A15"].font = label_font
    ws1["B15"].font = label_font
    ws1["C15"].font = label_font
    ws1["D15"].font = label_font
    for sev in ("critical", "high", "medium", "low", "informational"):
        info = summary["by_severity"].get(sev, {"total": 0, "passed": 0, "failed": 0})
        row_idx = ws1.max_row + 1
        ws1.append([sev.capitalize(), info["total"], info["passed"], info["failed"]])
        fill = SEVERITY_FILLS.get(sev)
        if fill:
            ws1.cell(row=row_idx, column=1).fill = fill

    ws1.column_dimensions["A"].width = 22
    ws1.column_dimensions["B"].width = 20

    # ── Sheet 2: Findings ──
    ws2 = wb.create_sheet("Findings")
    columns = [
        "Scan ID", "Target", "Benchmark", "Section", "Rule Title",
        "Severity", "Status", "Description", "Actual Output", "Expected Output",
        "Remediation", "Evaluation", "AI Advice", "Auditor Notes", "Auditor Override",
    ]
    ws2.append(columns)
    for col_idx in range(1, len(columns) + 1):
        ws2.cell(row=1, column=col_idx).font = label_font

    def _clean(val):
        """Strip illegal XML/Excel control characters from a string value."""
        if isinstance(val, str):
            return _ILLEGAL_XLSX_RE.sub('', val)
        return val

    for f in data["findings"]:
        if not include_passed and f["status"] == "PASS":
            continue
        row_idx = ws2.max_row + 1
        ws2.append([
            f["scan_id"],
            _clean(f["target_hostname"]),
            _clean(f["benchmark_name"]),
            f["section_number"],
            _clean(f["rule_title"]),
            f["severity"],
            f["status"],
            _clean(f.get("description", "")),
            _clean(f["actual_output"]),
            _clean(f["expected_output"]),
            _clean(f["remediation"]),
            _clean(f.get("evaluation_explanation", "")),
            _clean(f.get("ai_advice", "")),
            _clean(f.get("auditor_notes", "")),
            _clean(f.get("auditor_override", "")),
        ])
        # Color-code severity
        sev_fill = SEVERITY_FILLS.get(f["severity"])
        if sev_fill:
            ws2.cell(row=row_idx, column=6).fill = sev_fill
        # Color-code status
        if f["status"] == "PASS":
            ws2.cell(row=row_idx, column=7).fill = FILL_PASS
        elif f["status"] == "FAIL":
            ws2.cell(row=row_idx, column=7).fill = FILL_FAIL

    # Auto-filter
    if ws2.max_row > 1:
        ws2.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{ws2.max_row}"
    for col_idx in range(1, len(columns) + 1):
        ws2.column_dimensions[get_column_letter(col_idx)].width = 18

    # ── Sheet 3: Compliance by Target ──
    ws3 = wb.create_sheet("Compliance by Target")
    ws3.append(["Target", "IP Address", "Benchmark", "Compliance %", "Passed", "Failed", "Errors"])
    for col_idx in range(1, 8):
        ws3.cell(row=1, column=col_idx).font = label_font
    for target in data["targets"]:
        for scan in target["scans"]:
            ws3.append([
                target["hostname"],
                target["ip_address"],
                scan["benchmark_name"],
                scan["compliance_percentage"],
                scan["passed"],
                scan["failed"],
                scan["errors"],
            ])
    for col_idx in range(1, 8):
        ws3.column_dimensions[get_column_letter(col_idx)].width = 18

    # ── Sheet 4: Compliance by Category ──
    ws4 = wb.create_sheet("Compliance by Category")
    ws4.append(["Category", "Total", "Passed", "Failed", "Compliance %"])
    for col_idx in range(1, 6):
        ws4.cell(row=1, column=col_idx).font = label_font
    by_category = data.get("by_category", {})
    for cat_key in sorted(by_category.keys(), key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0, x)):
        info = by_category[cat_key]
        comp = round((info["passed"] / info["total"]) * 100, 1) if info["total"] > 0 else 0.0
        ws4.append([info.get("label", f"Section {cat_key}"), info["total"], info["passed"], info["failed"], comp])
    for col_idx in range(1, 6):
        ws4.column_dimensions[get_column_letter(col_idx)].width = 22

    # ── Sheet 5: Groups (when builder groups are present) ──
    builder_groups = data.get("builder_groups")
    if builder_groups:
        ws5 = wb.create_sheet("Groups")
        group_cols = ["Group", "Rule Section", "Rule Title", "Severity", "Status"]
        ws5.append(group_cols)
        for col_idx in range(1, len(group_cols) + 1):
            ws5.cell(row=1, column=col_idx).font = label_font

        # Build rule lookups from findings
        findings_by_rule: dict[int, dict] = {}
        for f in data["findings"]:
            if f.get("_rule_id") and f["_rule_id"] not in findings_by_rule:
                findings_by_rule[f["_rule_id"]] = f

        for bg in builder_groups:
            for rid in bg["rule_ids"]:
                fdata = findings_by_rule.get(rid, {})
                row_idx = ws5.max_row + 1
                ws5.append([
                    bg["name"],
                    fdata.get("section_number", ""),
                    _clean(fdata.get("rule_title", f"Rule #{rid}")),
                    fdata.get("severity", ""),
                    fdata.get("status", ""),
                ])
                sev_fill = SEVERITY_FILLS.get(fdata.get("severity", ""))
                if sev_fill:
                    ws5.cell(row=row_idx, column=4).fill = sev_fill
                if fdata.get("status") == "PASS":
                    ws5.cell(row=row_idx, column=5).fill = FILL_PASS
                elif fdata.get("status") == "FAIL":
                    ws5.cell(row=row_idx, column=5).fill = FILL_FAIL

        if ws5.max_row > 1:
            ws5.auto_filter.ref = f"A1:{get_column_letter(len(group_cols))}{ws5.max_row}"
        for col_idx in range(1, len(group_cols) + 1):
            ws5.column_dimensions[get_column_letter(col_idx)].width = 22

    # ── Apply text wrapping and column widths to Findings ──
    wrap_align = Alignment(wrap_text=True, vertical="top")
    for col_idx in [8, 9, 10, 11, 12, 13]:  # Description through AI Advice
        for row_idx in range(2, ws2.max_row + 1):
            cell = ws2.cell(row=row_idx, column=col_idx)
            cell.alignment = wrap_align
    ws2.column_dimensions["H"].width = 35  # Description
    ws2.column_dimensions["I"].width = 30  # Actual Output
    ws2.column_dimensions["J"].width = 30  # Expected Output
    ws2.column_dimensions["K"].width = 35  # Remediation
    ws2.column_dimensions["L"].width = 30  # Evaluation
    ws2.column_dimensions["M"].width = 30  # AI Advice

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# CSV generation
# ---------------------------------------------------------------------------

def generate_csv_report(data: dict, include_passed: bool = True) -> str:
    """Flat CSV export of all findings with auditor fields."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "scan_id", "target", "benchmark", "rule_section", "rule_title",
        "description", "severity", "status",
        "actual_output", "expected_output", "default_value", "rationale",
        "remediation", "evaluation_explanation", "ai_advice",
        "auditor_notes", "auditor_override",
    ])
    for f in data["findings"]:
        if not include_passed and f["status"] == "PASS":
            continue
        writer.writerow([
            f["scan_id"],
            f["target_hostname"],
            f["benchmark_name"],
            f["section_number"],
            f["rule_title"],
            f.get("description", ""),
            f["severity"],
            f["status"],
            f["actual_output"],
            f["expected_output"],
            f.get("default_value", ""),
            f.get("rationale", ""),
            f["remediation"],
            f.get("evaluation_explanation", ""),
            f.get("ai_advice", ""),
            f.get("auditor_notes", ""),
            f.get("auditor_override", ""),
        ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html_report(data: dict, include_passed: bool) -> str:
    """Self-contained interactive HTML dashboard — pure inline SVG charts, zero external deps."""
    findings = data["findings"]
    if not include_passed:
        findings = [f for f in findings if f["status"] != "PASS"]

    # ── Phase 2: grouped findings & builder metadata ──
    grouped_findings = _build_grouped_findings(data, findings)
    sections = data.get("sections") or {}
    group_summaries = data.get("group_summaries") or {}
    audience = data.get("audience", "technical")
    has_builder = bool(data.get("builder_groups"))

    # ── Generate all SVG charts (shared logic) ──
    charts = _generate_all_charts(data, grouped_findings)

    # ── Findings JSON for JS filtering/sorting engine ──
    findings_json = json.dumps(findings, default=str).replace("</", "<\\/")

    fp_summary = data.get("fp_summary", {})

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("report_dashboard.html.j2")

    return template.render(
        title=data.get("title") or f"Audit Report - {data.get('mission_name', '')}",
        client_name=data.get("client_name", ""),
        date_range=data.get("date_range", ""),
        generated_at=data.get("generated_at", ""),
        ai_summary=data.get("ai_summary", ""),
        summary=data["summary"],
        targets=data.get("targets", []),
        findings=findings,
        fp_summary=fp_summary,
        findings_json=findings_json,
        grouped_findings=grouped_findings,
        section_toggles=sections,
        group_summaries=group_summaries,
        audience=audience,
        has_builder=has_builder,
        **charts,
    )



# ---------------------------------------------------------------------------
# AI executive summary
# ---------------------------------------------------------------------------

async def generate_ai_summary(data: dict) -> str:
    """Use the LLM to produce a structured executive summary of the audit data."""
    summary = data["summary"]
    compliance = summary["overall_compliance"]

    # ---- severity breakdown ----
    sev_lines = "\n".join(
        f"  - {sev}: {info['total']} total, {info['passed']} passed, {info['failed']} failed "
        f"({round(info['passed'] / info['total'] * 100) if info['total'] else 0}% compliant)"
        for sev, info in summary["by_severity"].items()
    )

    # ---- category breakdown (top 5 worst) ----
    cats = summary.get("by_category", {})
    worst_cats = sorted(
        cats.items(),
        key=lambda x: x[1].get("failed", 0),
        reverse=True,
    )[:5]
    cat_lines = "\n".join(
        f"  - {cat}: {info.get('failed', 0)} failures out of {info.get('total', 0)} rules"
        for cat, info in worst_cats
    ) if worst_cats else "  (no category data available)"

    # ---- top failures with more context ----
    top_failures = [f for f in data["findings"] if f["status"] == "FAIL"][:15]
    failure_lines = "\n".join(
        f"  - [{f['severity'].upper()}] {f['section_number']} {f['rule_title']}"
        + (f"  — {f['description'][:120]}" if f.get("description") else "")
        for f in top_failures
    )

    # ---- risk level label ----
    if compliance >= 90:
        risk_label = "LOW"
    elif compliance >= 70:
        risk_label = "MODERATE"
    elif compliance >= 50:
        risk_label = "HIGH"
    else:
        risk_label = "CRITICAL"

    # ---- false-positive context ----
    fp_count = sum(
        1 for f in data["findings"]
        if f.get("auditor_status") in ("false_positive", "False Positive")
    )
    fp_note = (
        f"\n\nFalse Positives Flagged by Auditor: {fp_count}"
        if fp_count else ""
    )

    prompt = f"""You are a senior cybersecurity auditor writing an executive summary for a CIS benchmark configuration audit report.

──────────────────────────────────────────
AUDIT CONTEXT
──────────────────────────────────────────
Client:       {data.get('client_name', 'N/A')}
Mission:      {data.get('mission_name', 'N/A')}
Date Range:   {data.get('date_range', 'N/A')}
Benchmark:    {data.get('benchmark_name', 'CIS Benchmark')}
Target(s):    {', '.join(t.get('hostname', 'Unknown') for t in data.get('targets', [])) or 'N/A'}

──────────────────────────────────────────
KEY METRICS
──────────────────────────────────────────
Overall Compliance: {compliance}%  (Risk Level: {risk_label})
Total Rules:        {summary['total_rules']}
Passed:             {summary['passed']}
Failed:             {summary['failed']}
Errors:             {summary['errors']}{fp_note}

By Severity:
{sev_lines}

──────────────────────────────────────────
WORST CATEGORIES (by failure count)
──────────────────────────────────────────
{cat_lines}

──────────────────────────────────────────
TOP {len(top_failures)} FAILED RULES
──────────────────────────────────────────
{failure_lines}

──────────────────────────────────────────
INSTRUCTIONS
──────────────────────────────────────────
Write the executive summary using this EXACT structure (use these headings):

1. **Overview** — One paragraph stating the audit scope, benchmark, client, date,
   and the overall compliance percentage with the risk label.

2. **Key Findings** — Two paragraphs highlighting the most significant failures
   grouped by theme (e.g., authentication weaknesses, logging gaps, network
   exposure). Reference specific rule numbers.

3. **Risk Assessment** — One paragraph assessing the overall security posture,
   relating the compliance score to real-world risk. Mention which severity
   categories are most concerning.

4. **Recommendations** — A numbered list of 5-8 prioritised remediation actions,
   starting with quick wins and ending with strategic improvements. Each item
   should reference the related category or rule(s).

5. **Conclusion** — One short paragraph with a professional closing statement
   about next steps and timeline expectations.

TONE: Professional, objective, factual. Avoid marketing language.
LENGTH: 500-800 words total.
FORMAT: Use Markdown headings (##) and bullet/numbered lists."""

    system_prompt = (
        "You are a cybersecurity audit report writer specialising in CIS benchmark assessments. "
        "Produce clear, structured, professional executive summaries suitable for C-level "
        "and IT management audiences. Use precise language, cite specific rule numbers, "
        "and provide actionable recommendations."
    )

    try:
        return await llm_manager.invoke(prompt, system_prompt=system_prompt, task="reports")
    except Exception:
        logger.exception("AI summary generation failed")
        return "AI executive summary could not be generated. Please check LLM configuration."
