"""Core report generation logic — data aggregation and export to PDF, Excel, CSV, HTML."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, joinedload

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
        "ai_summary": None,
    }


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

    for f in data["findings"]:
        if not include_passed and f["status"] == "PASS":
            continue
        row_idx = ws2.max_row + 1
        ws2.append([
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
    """Self-contained interactive HTML report with embedded CSS/JS."""
    findings = data["findings"]
    if not include_passed:
        findings = [f for f in findings if f["status"] != "PASS"]

    summary = data["summary"]
    severity_order = ["critical", "high", "medium", "low"]

    # Build findings table rows
    finding_rows = ""
    for idx, f in enumerate(findings):
        sev_class = _esc(f["severity"])
        status_class = _esc(f["status"].lower())
        finding_rows += f"""
        <tr class="finding-row" data-severity="{_esc(f['severity'])}" data-status="{_esc(f['status'])}">
            <td>{f['scan_id']}</td>
            <td>{_esc(f['target_hostname'])}</td>
            <td>{_esc(f['benchmark_name'])}</td>
            <td>{_esc(f['section_number'])}</td>
            <td>{_esc(f['rule_title'])}</td>
            <td><span class="badge sev-{sev_class}">{_esc(f['severity'].upper())}</span></td>
            <td><span class="badge st-{status_class}">{_esc(f['status'])}</span></td>
            <td><button class="toggle-btn" onclick="toggleDetail('detail-{idx}')">&#9660;</button></td>
        </tr>
        <tr id="detail-{idx}" class="detail-row" style="display:none">
            <td colspan="8">
                <div class="detail-content">
                    <p><strong>Description:</strong> {_esc(f.get('description', ''))}</p>
                    <p><strong>Actual Output:</strong> <code>{_esc(f['actual_output'])}</code></p>
                    <p><strong>Expected Output:</strong> <code>{_esc(f['expected_output'])}</code></p>
                    <p><strong>Remediation:</strong> {_esc(f.get('remediation', ''))}</p>
                    <p><strong>Auditor Notes:</strong> {_esc(f.get('auditor_notes', ''))}</p>
                </div>
            </td>
        </tr>"""

    # Severity summary rows
    sev_rows = ""
    for sev in severity_order:
        info = summary["by_severity"].get(sev, {"total": 0, "passed": 0, "failed": 0})
        comp = round((info["passed"] / info["total"]) * 100, 1) if info["total"] > 0 else 0.0
        sev_rows += f"<tr><td class='sev-{sev}'>{sev.capitalize()}</td><td>{info['total']}</td><td>{info['passed']}</td><td>{info['failed']}</td><td>{comp}%</td></tr>\n"

    ai_section = ""
    if data.get("ai_summary"):
        ai_section = f"""<div class="section"><h2>AI Executive Summary</h2><p>{_esc(data['ai_summary'])}</p></div>"""

    title = data.get("title") or f"Audit Report — {data.get('mission_name', '')}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;color:#222;background:#f5f7fa;padding:20px}}
.container{{max-width:1200px;margin:0 auto;background:#fff;padding:30px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
h1{{font-size:1.6rem;margin-bottom:4px;color:#1a237e}}
h2{{font-size:1.2rem;margin:20px 0 10px;color:#283593}}
.meta{{color:#666;font-size:.9rem;margin-bottom:16px}}
.section{{margin-bottom:24px}}
.stats{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px}}
.stat-card{{background:#f0f4ff;padding:14px 20px;border-radius:6px;min-width:140px;text-align:center}}
.stat-card .val{{font-size:1.6rem;font-weight:700;color:#1a237e}}
.stat-card .lbl{{font-size:.8rem;color:#555}}
table{{width:100%;border-collapse:collapse;font-size:.85rem;margin-top:8px}}
th,td{{padding:8px 10px;border:1px solid #ddd;text-align:left}}
th{{background:#e8eaf6;position:sticky;top:0}}
.badge{{padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:600;color:#fff}}
.sev-critical{{background:#d32f2f}}.sev-high{{background:#e65100}}.sev-medium{{background:#f9a825;color:#333}}.sev-low{{background:#1565c0}}
.st-pass{{background:#2e7d32}}.st-fail{{background:#c62828}}.st-error{{background:#6a1b9a}}.st-manual_review{{background:#555}}
.toggle-btn{{cursor:pointer;background:none;border:1px solid #aaa;border-radius:4px;padding:2px 6px;font-size:.8rem}}
.detail-content{{padding:10px;background:#fafafa;border-radius:4px}}
.detail-content p{{margin:4px 0}}
code{{background:#eee;padding:2px 4px;border-radius:3px;font-size:.82rem}}
.filters{{margin:10px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
.filters select,.filters button{{padding:4px 10px;border-radius:4px;border:1px solid #aaa;font-size:.85rem}}
</style>
</head>
<body>
<div class="container">
    <h1>{_esc(title)}</h1>
    <p class="meta">{_esc(data.get('client_name',''))} &mdash; {_esc(data.get('date_range',''))} &mdash; Generated {_esc(data.get('generated_at',''))}</p>

    {ai_section}

    <div class="section">
        <h2>Compliance Overview</h2>
        <div class="stats">
            <div class="stat-card"><div class="val">{summary['overall_compliance']}%</div><div class="lbl">Overall Compliance</div></div>
            <div class="stat-card"><div class="val">{summary['total_rules']}</div><div class="lbl">Total Rules</div></div>
            <div class="stat-card"><div class="val">{summary['passed']}</div><div class="lbl">Passed</div></div>
            <div class="stat-card"><div class="val">{summary['failed']}</div><div class="lbl">Failed</div></div>
            <div class="stat-card"><div class="val">{summary['errors']}</div><div class="lbl">Errors</div></div>
        </div>
    </div>

    <div class="section">
        <h2>Compliance by Severity</h2>
        <table><thead><tr><th>Severity</th><th>Total</th><th>Passed</th><th>Failed</th><th>Compliance</th></tr></thead>
        <tbody>{sev_rows}</tbody></table>
    </div>

    <div class="section">
        <h2>Findings</h2>
        <div class="filters">
            <label>Severity: <select id="fltSev"><option value="">All</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
            <label>Status: <select id="fltSt"><option value="">All</option><option value="PASS">Pass</option><option value="FAIL">Fail</option><option value="ERROR">Error</option></select></label>
            <button onclick="applyFilters()">Apply</button>
            <button onclick="expandAll()">Expand All</button>
            <button onclick="collapseAll()">Collapse All</button>
        </div>
        <table>
        <thead><tr><th onclick="sortTable(0)">Scan</th><th onclick="sortTable(1)">Target</th><th onclick="sortTable(2)">Benchmark</th><th onclick="sortTable(3)">Section</th><th onclick="sortTable(4)">Rule</th><th onclick="sortTable(5)">Severity</th><th onclick="sortTable(6)">Status</th><th></th></tr></thead>
        <tbody id="findingsBody">{finding_rows}</tbody>
        </table>
    </div>
</div>
<script>
function toggleDetail(id){{var el=document.getElementById(id);el.style.display=el.style.display==='none'?'table-row':'none'}}
function expandAll(){{document.querySelectorAll('.detail-row').forEach(r=>r.style.display='table-row')}}
function collapseAll(){{document.querySelectorAll('.detail-row').forEach(r=>r.style.display='none')}}
function applyFilters(){{
    var sev=document.getElementById('fltSev').value;
    var st=document.getElementById('fltSt').value;
    document.querySelectorAll('.finding-row').forEach(r=>{{
        var show=true;
        if(sev&&r.dataset.severity!==sev)show=false;
        if(st&&r.dataset.status!==st)show=false;
        r.style.display=show?'':'none';
        var next=r.nextElementSibling;
        if(next&&next.classList.contains('detail-row'))next.style.display='none';
    }});
}}
var sortDir={{}};
function sortTable(col){{
    var body=document.getElementById('findingsBody');
    var rows=Array.from(body.querySelectorAll('.finding-row'));
    sortDir[col]=!sortDir[col];
    rows.sort(function(a,b){{
        var at=a.children[col].textContent.trim();
        var bt=b.children[col].textContent.trim();
        return sortDir[col]?at.localeCompare(bt):bt.localeCompare(at);
    }});
    rows.forEach(function(r){{
        var detail=r.nextElementSibling;
        body.appendChild(r);
        if(detail&&detail.classList.contains('detail-row'))body.appendChild(detail);
    }});
}}
</script>
</body>
</html>"""
    return html


def _esc(text: str | None) -> str:
    """HTML escaping for safe output in element content and attribute values."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
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
        return await llm_manager.invoke(prompt, system_prompt=system_prompt)
    except Exception:
        logger.exception("AI summary generation failed")
        return "AI executive summary could not be generated. Please check LLM configuration."
