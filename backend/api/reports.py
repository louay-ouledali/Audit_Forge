"""API endpoints for report generation."""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.core.report_generator import (
    aggregate_report_data,
    generate_ai_summary,
    generate_csv_report,
    generate_excel_report,
    generate_html_report,
    generate_pdf_report,
)
from backend.database import get_db
from backend.core.auth import get_current_user
from backend.core.trail import log_action
from backend.models.user import User
from backend.schemas.report import (
    AISummaryRequest,
    AISummaryResponse,
    AutoGroupRequest,
    BuilderFindingsRequest,
    BuilderPreviewRequest,
    GroupSummaryRequest,
    GroupSummaryResponse,
    ReportGenerateRequest,
    RuleGroup,  # UNUSED — safe to remove
)

logger = logging.getLogger("auditforge.api.reports")

router = APIRouter(prefix="/reports", tags=["reports"])

VALID_SCOPES = {"scan", "target", "mission", "custom"}
VALID_FORMATS = {"pdf", "excel", "csv", "html"}

_FILE_EXTENSIONS = {"pdf": "pdf", "excel": "xlsx", "csv": "csv", "html": "html"}


def _inject_builder_data(data: dict, payload) -> None:
    """Copy Phase 2 builder fields (groups, audience, sections, summaries) into the report data dict."""
    if payload.groups:
        data["builder_groups"] = [
            {"name": g.name, "rule_ids": g.rule_ids} for g in payload.groups
        ]
    else:
        data["builder_groups"] = None

    data["audience"] = payload.audience or "technical"

    if payload.sections:
        data["sections"] = payload.sections
    else:
        data["sections"] = None

    if payload.group_summaries:
        data["group_summaries"] = payload.group_summaries
    else:
        data["group_summaries"] = None


def _build_report_filename(data: dict, fmt: str) -> str:
    """Build a smart filename: AuditForge_{Client}_{Mission}_{Date}.{ext}"""
    ext = _FILE_EXTENSIONS.get(fmt, fmt)
    parts = ["AuditForge"]
    client = (data.get("client_name") or "").strip()
    mission = (data.get("mission_name") or "").strip()
    if client:
        parts.append(re.sub(r'[^\w\s-]', '', client).replace(' ', '_')[:30])
    if mission:
        parts.append(re.sub(r'[^\w\s-]', '', mission).replace(' ', '_')[:40])
    parts.append(datetime.now(timezone.utc).strftime("%Y%m%d"))
    return "_".join(parts) + f".{ext}"


@router.post("/generate")
async def generate_report(payload: ReportGenerateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Generate a report file based on scope and format."""
    if payload.scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"Invalid scope. Must be one of: {', '.join(VALID_SCOPES)}")
    if payload.format not in VALID_FORMATS:
        raise HTTPException(status_code=400, detail=f"Invalid format. Must be one of: {', '.join(VALID_FORMATS)}")
    if payload.scope != "custom" and payload.scope_id is None:
        raise HTTPException(status_code=400, detail="scope_id is required for non-custom scopes")
    if payload.scope == "custom" and not payload.scan_ids:
        raise HTTPException(status_code=400, detail="scan_ids is required for custom scope")

    data = aggregate_report_data(payload.scope, payload.scope_id, payload.scan_ids, db,
                                  excluded_rule_ids=payload.excluded_rule_ids,
                                  severity_filter=payload.severity_filter)

    if not data or not data.get("scans"):
        raise HTTPException(status_code=404, detail="No scans found for the given scope")

    if payload.title:
        data["title"] = payload.title

    if payload.include_ai_summary:
        data["ai_summary"] = await generate_ai_summary(data)

    # Inject Phase 2 builder data (groups, audience, sections, summaries)
    _inject_builder_data(data, payload)

    # Log report generation to Forge Trail
    mission_id = payload.scope_id if payload.scope == "mission" else None
    if mission_id:
        try:
            log_action(db, user=current_user, mission_id=mission_id, action="report_generated", entity_type="report", details={"format": payload.format})
        except Exception as exc:
            logger.warning("Trail log failed: %s", exc)

    filename = _build_report_filename(data, payload.format)

    if payload.format == "pdf":
        try:
            content = generate_pdf_report(data, payload.include_passed_rules, db)
        except Exception:
            logger.exception("PDF generation failed")
            raise HTTPException(status_code=500, detail="PDF generation failed")
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if payload.format == "excel":
        content = generate_excel_report(data, payload.include_passed_rules)
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if payload.format == "csv":
        content = generate_csv_report(data, payload.include_passed_rules)
        return StreamingResponse(
            io.StringIO(content),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # html
    content = generate_html_report(data, payload.include_passed_rules, db=db)
    return StreamingResponse(
        io.StringIO(content),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/ai-summary", response_model=AISummaryResponse)
async def generate_ai_summary_endpoint(payload: AISummaryRequest, db: Session = Depends(get_db)):
    """Generate AI executive summary only (preview)."""
    if payload.scope not in ("scan", "target", "mission", "custom"):
        raise HTTPException(status_code=400, detail="Scope must be scan, target, mission, or custom")

    if payload.scope == "custom":
        if not payload.scan_ids:
            raise HTTPException(status_code=400, detail="scan_ids required for custom scope")
        data = aggregate_report_data("custom", None, payload.scan_ids, db)
    else:
        if payload.scope_id is None:
            raise HTTPException(status_code=400, detail="scope_id required for non-custom scopes")
        data = aggregate_report_data(payload.scope, payload.scope_id, None, db)

    if not data or not data.get("scans"):
        raise HTTPException(status_code=404, detail="No scans found for the given scope")

    summary_text = await generate_ai_summary(data)
    return AISummaryResponse(summary=summary_text)


# Report Builder endpoints

@router.post("/builder/findings")
def builder_get_findings(payload: BuilderFindingsRequest, db: Session = Depends(get_db)):
    """Return all findings for the selected scans (for rule check/uncheck in the builder)."""
    from backend.models.finding import Finding
    from backend.models.rule import Rule
    from backend.models.scan import Scan
    from backend.models.target import Target
    from backend.models.benchmark import Benchmark

    if not payload.scan_ids:
        raise HTTPException(status_code=400, detail="scan_ids is required")

    findings = (
        db.query(Finding)
        .filter(Finding.scan_id.in_(payload.scan_ids))
        .all()
    )

    # Batch-load related entities to avoid N+1 queries
    rule_ids = {f.rule_id for f in findings if f.rule_id}
    rules_map: dict[int, Rule] = {}
    if rule_ids:
        for r in db.query(Rule).filter(Rule.id.in_(rule_ids)).all():
            rules_map[r.id] = r

    scans_list = db.query(Scan).filter(Scan.id.in_(payload.scan_ids)).all()
    scans_map: dict[int, Scan] = {s.id: s for s in scans_list}

    target_ids = {s.target_id for s in scans_list if s.target_id}
    targets_map: dict[int, Target] = {}
    if target_ids:
        for t in db.query(Target).filter(Target.id.in_(target_ids)).all():
            targets_map[t.id] = t

    benchmark_ids = {s.benchmark_id for s in scans_list if s.benchmark_id}
    benchmarks_map: dict[int, Benchmark] = {}
    if benchmark_ids:
        for b in db.query(Benchmark).filter(Benchmark.id.in_(benchmark_ids)).all():
            benchmarks_map[b.id] = b

    results = []
    for f in findings:
        rule = rules_map.get(f.rule_id)
        scan = scans_map.get(f.scan_id)
        target = targets_map.get(scan.target_id) if scan else None
        benchmark = benchmarks_map.get(scan.benchmark_id) if scan else None

        results.append({
            "finding_id": f.id,
            "rule_id": f.rule_id,
            "scan_id": f.scan_id,
            "section_number": rule.section_number if rule else "",
            "rule_title": rule.title if rule else "",
            "description": rule.description if rule else "",
            "severity": (f.severity or (rule.severity if rule else "medium") or "medium").lower(),
            "status": (f.status or "").upper(),
            "target_hostname": target.hostname if target else "",
            "benchmark_name": benchmark.name if benchmark else "",
        })

    return {"data": results, "total": len(results)}


@router.post("/builder/preview")
def builder_preview(payload: BuilderPreviewRequest, db: Session = Depends(get_db)):
    """Generate an HTML preview for the Report Builder (rendered inline, not downloaded)."""
    data = aggregate_report_data(
        "custom", None, payload.scan_ids, db,
        excluded_rule_ids=payload.excluded_rule_ids,
        severity_filter=getattr(payload, 'severity_filter', None),
    )

    if not data or not data.get("scans"):
        raise HTTPException(status_code=404, detail="No scans found for the given scan IDs")

    if payload.title:
        data["title"] = payload.title

    # Inject Phase 2 builder data (groups, audience, sections, summaries)
    _inject_builder_data(data, payload)

    html_content = generate_html_report(data, payload.include_passed_rules, db=db)
    return StreamingResponse(
        io.StringIO(html_content),
        media_type="text/html",
    )


@router.post("/builder/auto-group")
def builder_auto_group(payload: AutoGroupRequest, db: Session = Depends(get_db)):
    """Auto-group rules by keyword-based category detection (v2 — weighted scoring)."""
    from backend.models.finding import Finding
    from backend.models.rule import Rule
    from backend.core.rule_categorizer import auto_tag_rule, prettify_category

    if not payload.scan_ids:
        raise HTTPException(status_code=400, detail="scan_ids is required")

    excluded = set(payload.excluded_rule_ids or [])

    # Fetch unique rule ids from findings
    findings = (
        db.query(Finding.rule_id)
        .filter(Finding.scan_id.in_(payload.scan_ids))
        .distinct()
        .all()
    )

    rule_ids = [f.rule_id for f in findings if f.rule_id not in excluded]

    # Batch-load all rules in one query (optimization)
    rules_by_id: dict[int, Rule] = {}
    if rule_ids:
        rules = db.query(Rule).filter(Rule.id.in_(rule_ids)).all()
        rules_by_id = {r.id: r for r in rules}

    # Group by category using the weighted keyword tagger
    groups: dict[str, list[int]] = {}
    for rid in rule_ids:
        rule = rules_by_id.get(rid)
        if rule:
            tags = auto_tag_rule(
                rule.title or "",
                rule.description or "",
                rule.audit_description_raw or "",
                rule.remediation_description_raw or "",
                section_number=rule.section_number or "",
            )
            if tags:
                category = tags[0]  # highest-scored tag
            elif rule.section_number:
                top = rule.section_number.split(".")[0]
                category = f"section_{top}"
            else:
                category = "other"
        else:
            category = "other"

        display_name = prettify_category(category)
        groups.setdefault(display_name, []).append(rid)

    # Sort groups: alphabetical, "Other" last
    sorted_groups = []
    for name in sorted(groups.keys()):
        if name.lower() == "other":
            continue
        sorted_groups.append({"name": name, "rule_ids": groups[name]})
    if "Other" in groups:
        sorted_groups.append({"name": "Other", "rule_ids": groups["Other"]})

    return {"groups": sorted_groups, "total_rules": len(rule_ids), "total_groups": len(sorted_groups)}


@router.post("/builder/group-summary")
async def builder_group_summary(payload: GroupSummaryRequest, db: Session = Depends(get_db)):
    """Generate an AI summary for a specific rule group."""
    from backend.models.finding import Finding
    from backend.models.rule import Rule

    if not payload.rule_ids:
        raise HTTPException(status_code=400, detail="rule_ids is required")

    # Gather rule details — batch-load to avoid N+1
    rules_by_id = {r.id: r for r in db.query(Rule).filter(Rule.id.in_(payload.rule_ids)).all()}
    findings_by_rule: dict[int, Finding] = {}
    if payload.scan_ids:
        for f in db.query(Finding).filter(Finding.rule_id.in_(payload.rule_ids), Finding.scan_id.in_(payload.scan_ids)).all():
            findings_by_rule.setdefault(f.rule_id, f)

    rules_info = []
    for rid in payload.rule_ids:
        rule = rules_by_id.get(rid)
        if not rule:
            continue
        finding = findings_by_rule.get(rid)
        rules_info.append({
            "title": rule.title or f"Rule #{rid}",
            "section": rule.section_number or "",
            "severity": (finding.severity if finding and finding.severity else (rule.severity or "medium")).lower(),
            "status": (finding.status if finding else "UNKNOWN").upper(),
            "description": (rule.description or "")[:200],
        })

    audience_labels = {
        "executive": "non-technical executive who needs business impact and risk context",
        "technical": "technical IT security analyst who needs specific controls and remediation details",
        "compliance": "compliance officer who needs regulatory alignment and control mapping",
    }
    audience_desc = audience_labels.get(payload.audience, audience_labels["technical"])

    rules_text = "\n".join(
        f"- [{r['section']}] {r['title']} (Severity: {r['severity']}, Status: {r['status']})"
        for r in rules_info
    )
    pass_count = sum(1 for r in rules_info if r["status"] == "PASS")
    fail_count = sum(1 for r in rules_info if r["status"] == "FAIL")

    prompt = (
        f"Write a concise summary (3-5 sentences) for the audit section \"{payload.group_name}\" "
        f"targeting a {audience_desc}.\n\n"
        f"Section contains {len(rules_info)} rules: {pass_count} passed, {fail_count} failed.\n\n"
        f"Rules:\n{rules_text}\n\n"
        f"Focus on key findings, overall compliance posture, and recommended priorities. "
        f"Do NOT use markdown formatting. Write plain text only."
    )

    try:
        from backend.ai.llm_manager import llm_manager
        summary = await llm_manager.invoke(prompt, task="reports", timeout=60.0)
        return GroupSummaryResponse(summary=summary.strip())
    except Exception as exc:
        logger.warning("Group summary generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"AI summary failed: {exc}")
