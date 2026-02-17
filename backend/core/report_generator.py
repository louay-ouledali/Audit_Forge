"""Core report generation logic — data aggregation and export to PDF, Excel, CSV, HTML."""
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
FILL_PASS = PatternFill(start_color="90EE90", end_color="90EE90", fill_type="solid")
FILL_FAIL = PatternFill(start_color="FFB6C1", end_color="FFB6C1", fill_type="solid")

SEVERITY_FILLS = {
    "critical": FILL_CRITICAL,
    "high": FILL_HIGH,
    "medium": FILL_MEDIUM,
    "low": FILL_LOW,
}


# ---------------------------------------------------------------------------
# Data aggregation
# ---------------------------------------------------------------------------

def aggregate_report_data(
    scope: str,
    scope_id: int | None,
    scan_ids: list[int] | None,
    db: Session,
) -> dict:
    """Query the database and return a normalised report data dict."""
    scans: list[Scan] = []

    if scope == "scan":
        scan = (
            db.query(Scan)
            .options(joinedload(Scan.target).joinedload(Target.mission).joinedload(Mission.client))
            .filter(Scan.id == scope_id)
            .first()
        )
        if scan:
            scans = [scan]

    elif scope == "target":
        target = (
            db.query(Target)
            .options(joinedload(Target.mission).joinedload(Mission.client))
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
            target_ids = [t.id for t in db.query(Target).filter(Target.mission_id == mission.id).all()]
            if target_ids:
                scans = db.query(Scan).filter(Scan.target_id.in_(target_ids)).all()

    elif scope == "custom":
        if scan_ids:
            scans = (
                db.query(Scan)
                .options(joinedload(Scan.target).joinedload(Target.mission).joinedload(Mission.client))
                .filter(Scan.id.in_(scan_ids))
                .all()
            )

    # Determine client / mission context from the first available scan
    client_name = ""
    mission_name = ""
    if scans:
        first_scan = scans[0]
        target_obj = db.query(Target).filter(Target.id == first_scan.target_id).first()
        if target_obj:
            mission_obj = db.query(Mission).filter(Mission.id == target_obj.mission_id).first()
            if mission_obj:
                mission_name = mission_obj.name or ""
                client_obj = db.query(Client).filter(Client.id == mission_obj.client_id).first()
                if client_obj:
                    client_name = client_obj.name or ""

    # Build per-target structure
    targets_map: dict[int, dict] = {}
    for scan in scans:
        target_obj = db.query(Target).filter(Target.id == scan.target_id).first()
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
        benchmark = db.query(Benchmark).filter(Benchmark.id == scan.benchmark_id).first()
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
        for f in db_findings:
            rule = db.query(Rule).filter(Rule.id == f.rule_id).first()
            scan_obj = db.query(Scan).filter(Scan.id == f.scan_id).first()
            target_obj = db.query(Target).filter(Target.id == scan_obj.target_id).first() if scan_obj else None
            benchmark = db.query(Benchmark).filter(Benchmark.id == scan_obj.benchmark_id).first() if scan_obj else None

            sev = (f.severity or (rule.severity if rule else "medium") or "medium").lower()
            status = (f.status or "").upper()

            findings_rows.append({
                "scan_id": f.scan_id,
                "target_hostname": target_obj.hostname if target_obj else "",
                "benchmark_name": benchmark.name if benchmark else "",
                "section_number": rule.section_number if rule else "",
                "rule_title": rule.title if rule else "",
                "description": rule.description if rule else "",
                "severity": sev,
                "status": status,
                "actual_output": f.actual_output or "",
                "expected_output": f.expected_output or "",
                "remediation": rule.remediation_description_raw if rule else "",
                "auditor_notes": f.auditor_notes or "",
                "auditor_override": f.auditor_override or "",
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
        "ai_summary": None,
    }


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def generate_pdf_report(data: dict, include_passed: bool, db: Session) -> bytes:
    """Render an HTML template with Jinja2 and convert to PDF via WeasyPrint."""
    from weasyprint import HTML  # imported here to isolate heavy dep
    from backend.core.chart_helpers import generate_donut_svg, generate_hbar_svg

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("report.html.j2")

    if not include_passed:
        data = {**data, "findings": [f for f in data["findings"] if f["status"] != "PASS"]}

    # Generate SVG charts for the PDF
    summary = data["summary"]
    data["chart_donut"] = generate_donut_svg([
        {"label": "Passed", "value": summary["passed"], "color": "#22c55e"},
        {"label": "Failed", "value": summary["failed"], "color": "#ef4444"},
        {"label": "Errors", "value": summary["errors"], "color": "#8b5cf6"},
    ], title="Results Distribution")

    sev_items = []
    for sev in ("critical", "high", "medium", "low"):
        info = summary["by_severity"].get(sev, {"total": 0, "passed": 0})
        comp = round((info["passed"] / info["total"]) * 100, 1) if info["total"] > 0 else 0
        colors = {"critical": "#dc2626", "high": "#ea580c", "medium": "#d97706", "low": "#2563eb"}
        sev_items.append({"label": sev.capitalize(), "value": comp, "color": colors[sev]})
    data["chart_severity"] = generate_hbar_svg(sev_items, title="Compliance by Severity")

    target_items = []
    for t in data.get("by_target", []):
        c = t["compliance"]
        color = "#22c55e" if c >= 80 else "#f59e0b" if c >= 50 else "#ef4444"
        target_items.append({"label": t["hostname"] or t["ip_address"], "value": c, "color": color})
    data["chart_targets"] = generate_hbar_svg(target_items, title="Compliance by Target") if len(target_items) > 1 else ""

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

    ws1.append(["Audit Report — Executive Summary"])
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
    for sev in ("critical", "high", "medium", "low"):
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
        "Severity", "Status", "Actual Output", "Expected Output", "Remediation",
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
            _clean(f["actual_output"]),
            _clean(f["expected_output"]),
            _clean(f["remediation"]),
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
    ws4.append(["Severity", "Total", "Passed", "Failed", "Compliance %"])
    for col_idx in range(1, 6):
        ws4.cell(row=1, column=col_idx).font = label_font
    for sev in ("critical", "high", "medium", "low"):
        info = summary["by_severity"].get(sev, {"total": 0, "passed": 0, "failed": 0})
        comp = round((info["passed"] / info["total"]) * 100, 1) if info["total"] > 0 else 0.0
        row_idx = ws4.max_row + 1
        ws4.append([sev.capitalize(), info["total"], info["passed"], info["failed"], comp])
        fill = SEVERITY_FILLS.get(sev)
        if fill:
            ws4.cell(row=row_idx, column=1).fill = fill
    for col_idx in range(1, 6):
        ws4.column_dimensions[get_column_letter(col_idx)].width = 18

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# CSV generation
# ---------------------------------------------------------------------------

def generate_csv_report(data: dict) -> str:
    """Flat CSV export of all findings."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "scan_id", "target", "benchmark", "rule_section", "rule_title",
        "severity", "status", "actual_output", "expected_output", "remediation",
    ])
    for f in data["findings"]:
        writer.writerow([
            f["scan_id"],
            f["target_hostname"],
            f["benchmark_name"],
            f["section_number"],
            f["rule_title"],
            f["severity"],
            f["status"],
            f["actual_output"],
            f["expected_output"],
            f["remediation"],
        ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html_report(data: dict, include_passed: bool) -> str:
    """Self-contained interactive HTML dashboard — pure inline SVG charts, zero external deps."""
    from backend.core.chart_helpers import (
        generate_donut_svg,
        generate_hbar_svg,
        generate_stacked_hbar_svg,
    )

    findings = data["findings"]
    if not include_passed:
        findings = [f for f in findings if f["status"] != "PASS"]

    summary = data["summary"]

    # ── SVG Charts (generated server-side, embedded inline) ──
    chart_donut = generate_donut_svg([
        {"label": "Passed", "value": summary["passed"], "color": "#22c55e"},
        {"label": "Failed", "value": summary["failed"], "color": "#ef4444"},
        {"label": "Errors", "value": summary["errors"], "color": "#8b5cf6"},
    ], title="Results Distribution")

    sev_items = []
    for sev in ("critical", "high", "medium", "low"):
        info = summary["by_severity"].get(sev, {"total": 0, "passed": 0})
        comp = round((info["passed"] / info["total"]) * 100, 1) if info["total"] > 0 else 0
        colors = {"critical": "#dc2626", "high": "#ea580c", "medium": "#d97706", "low": "#2563eb"}
        sev_items.append({"label": sev.capitalize(), "value": comp, "color": colors[sev]})
    chart_severity = generate_hbar_svg(sev_items, title="Compliance by Severity")

    target_items = []
    for t in data.get("by_target", []):
        c = t["compliance"]
        color = "#22c55e" if c >= 80 else "#f59e0b" if c >= 50 else "#ef4444"
        target_items.append({"label": t["hostname"] or t["ip_address"], "value": c, "color": color})
    chart_targets = generate_hbar_svg(target_items, title="Compliance by Target") if len(target_items) > 1 else ""

    cat_items = []
    by_cat = data.get("by_category", {})
    for cat_name, cat_info in by_cat.items():
        cat_items.append({"label": cat_name, "passed": cat_info.get("passed", 0), "failed": cat_info.get("failed", 0)})
    chart_categories = generate_stacked_hbar_svg(cat_items, title="Findings by Category") if cat_items else ""

    # ── Findings JSON for JS filtering/sorting engine ──
    # Escape </script> to prevent XSS when embedding in <script> tag
    findings_json = json.dumps(findings, default=str).replace("</", "<\\/")

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("report_dashboard.html.j2")

    return template.render(
        title=data.get("title") or f"Audit Report — {data.get('mission_name', '')}",
        client_name=data.get("client_name", ""),
        date_range=data.get("date_range", ""),
        generated_at=data.get("generated_at", ""),
        ai_summary=data.get("ai_summary", ""),
        summary=summary,
        targets=data.get("targets", []),
        findings=findings,
        chart_donut=chart_donut,
        chart_severity=chart_severity,
        chart_targets=chart_targets,
        chart_categories=chart_categories,
        findings_json=findings_json,
    )



# ---------------------------------------------------------------------------
# AI executive summary
# ---------------------------------------------------------------------------

async def generate_ai_summary(data: dict) -> str:
    """Use the LLM to produce an executive summary of the audit data."""
    summary = data["summary"]
    sev_lines = "\n".join(
        f"  - {sev}: {info['total']} total, {info['passed']} passed, {info['failed']} failed"
        for sev, info in summary["by_severity"].items()
    )
    top_failures = [f for f in data["findings"] if f["status"] == "FAIL"][:10]
    failure_lines = "\n".join(
        f"  - [{f['severity'].upper()}] {f['section_number']} {f['rule_title']}"
        for f in top_failures
    )

    prompt = f"""You are a senior cybersecurity auditor. Write a concise executive summary for a configuration audit report.

Key Metrics:
- Overall Compliance: {summary['overall_compliance']}%
- Total Rules Evaluated: {summary['total_rules']}
- Passed: {summary['passed']}, Failed: {summary['failed']}, Errors: {summary['errors']}

By Severity:
{sev_lines}

Top Failed Rules:
{failure_lines}

Client: {data.get('client_name', 'N/A')}
Mission: {data.get('mission_name', 'N/A')}
Date Range: {data.get('date_range', 'N/A')}

Write 3-5 paragraphs summarising the findings, highlighting critical risks, and providing high-level recommendations. Be professional and factual."""

    system_prompt = "You are a cybersecurity audit report writer. Produce clear, professional executive summaries."

    try:
        return await llm_manager.invoke(prompt, system_prompt=system_prompt, task="reports")
    except Exception:
        logger.exception("AI summary generation failed")
        return "AI executive summary could not be generated. Please check LLM configuration."
