from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.config import PROJECT_ROOT
from backend.core.phase1_parser import compute_pdf_hash, run_phase1
from backend.core.phase2_enricher import is_paused, request_pause, run_phase2
from backend.core.phase3_validator import (
    apply_corrections as phase3_apply,
    clear_pause as phase3_clear_pause,
    dismiss_corrections as phase3_dismiss,
    is_paused as phase3_is_paused,
    request_pause as phase3_request_pause,
    run_phase3,
)
from backend.core.verification_engine import run_verification
from backend.database import get_db
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.rule_tag import RuleTag
from backend.models.verification_report import VerificationReport
from backend.schemas.benchmark import (
    BenchmarkDetailEnvelope,
    BenchmarkImportResponse,
    BenchmarkListResponse,
    BenchmarkResponse,
    BenchmarkStatusResponse,
    EnrichStatusResponse,
    ValidateStatusResponse,
    ValidationResultsResponse,
    ValidationResultItem,
    ValidationCorrection,
    VerifyStatusResponse,
)
from backend.schemas.rule import VerificationReportResponse, VerificationResultsResponse

logger = logging.getLogger("auditforge.api.benchmarks")

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])

BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks"
BENCHMARKS_DIR.mkdir(exist_ok=True)


@router.get("", response_model=BenchmarkListResponse)
def list_benchmarks(db: Session = Depends(get_db)):
    benchmarks = db.query(Benchmark).order_by(Benchmark.id.desc()).all()
    return {"data": [BenchmarkResponse.model_validate(b) for b in benchmarks], "total": len(benchmarks)}


@router.post("/import", response_model=BenchmarkImportResponse)
async def import_benchmark(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Sanitize filename to prevent path traversal
    safe_filename = Path(file.filename).name
    if not safe_filename or safe_filename.startswith(".") or "/" in file.filename or "\\" in file.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Save to benchmarks directory
    pdf_path = BENCHMARKS_DIR / safe_filename
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Compute hash for dedup
    pdf_hash = compute_pdf_hash(pdf_path)
    existing = db.query(Benchmark).filter(Benchmark.pdf_hash == pdf_hash).first()
    if existing:
        pdf_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail=f"This PDF has already been imported as benchmark '{existing.name}' (ID: {existing.id})",
        )

    # Create benchmark record
    benchmark = Benchmark(
        name=safe_filename.replace(".pdf", ""),
        version="unknown",
        platform="unknown",
        platform_family="other",
        pdf_filename=safe_filename,
        pdf_hash=pdf_hash,
        phase1_status="pending",
    )
    db.add(benchmark)
    db.commit()
    db.refresh(benchmark)

    # Start Phase 1 as background task
    background_tasks.add_task(run_phase1, benchmark.id, pdf_path)

    return BenchmarkImportResponse(benchmark_id=benchmark.id)


@router.get("/{benchmark_id}", response_model=BenchmarkDetailEnvelope)
def get_benchmark(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return {"data": BenchmarkResponse.model_validate(benchmark), "message": "success"}


@router.get("/{benchmark_id}/status", response_model=BenchmarkStatusResponse)
def get_benchmark_status(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return BenchmarkStatusResponse(
        id=benchmark.id,
        phase1_status=benchmark.phase1_status or "pending",
        phase2_status=benchmark.phase2_status or "pending",
        verification_status=benchmark.verification_status or "pending",
        is_ready=benchmark.is_ready or False,
        total_rules=benchmark.total_rules or 0,
    )


@router.delete("/{benchmark_id}")
def delete_benchmark(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    # Delete PDF file if exists
    if benchmark.pdf_filename:
        pdf_path = BENCHMARKS_DIR / benchmark.pdf_filename
        pdf_path.unlink(missing_ok=True)
    db.delete(benchmark)
    db.commit()
    return {"data": None, "message": "Benchmark deleted"}


@router.get("/{benchmark_id}/rules", response_model=dict)
def list_benchmark_rules(
    benchmark_id: int,
    category: str | None = Query(None),
    profile: str | None = Query(None),
    severity: str | None = Query(None),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    query = db.query(Rule).filter(Rule.benchmark_id == benchmark_id)

    if severity:
        query = query.filter(Rule.severity == severity)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Rule.title.ilike(search_term)) | (Rule.section_number.ilike(search_term))
        )
    if category:
        from backend.models.rule_tag import RuleTag
        query = query.join(RuleTag).filter(RuleTag.tag_id == category)
    if profile:
        query = query.filter(Rule.profile_applicability.ilike(f"%{profile}%"))

    rules = query.order_by(Rule.section_number).all()

    from backend.schemas.rule import RuleResponse, RuleTagResponse
    result = []
    for r in rules:
        rule_resp = RuleResponse.model_validate(r)
        rule_resp.tags = [RuleTagResponse.model_validate(t) for t in r.tags]
        result.append(rule_resp)

    return {"data": result, "total": len(result)}


# ── Phase 1: Export / Import Rules ──


@router.get("/{benchmark_id}/rules/export")
def export_rules(benchmark_id: int, db: Session = Depends(get_db)):
    """Export all Phase 1 rules as a downloadable JSON file."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    rules = (
        db.query(Rule)
        .filter(Rule.benchmark_id == benchmark_id)
        .order_by(Rule.section_number)
        .all()
    )

    export_data = {
        "export_type": "phase1_rules",
        "benchmark": {
            "name": benchmark.name,
            "version": benchmark.version,
            "platform": benchmark.platform,
            "platform_family": benchmark.platform_family,
        },
        "total_rules": len(rules),
        "rules": [],
    }
    for r in rules:
        tags = [{"tag_id": t.tag_id, "source": t.source} for t in r.tags]
        export_data["rules"].append(
            {
                "section_number": r.section_number,
                "title": r.title,
                "description": r.description,
                "rationale": r.rationale,
                "profile_applicability": r.profile_applicability,
                "assessment_type": r.assessment_type,
                "default_value": r.default_value,
                "references_json": r.references_json,
                "cis_controls": r.cis_controls,
                "audit_description_raw": r.audit_description_raw,
                "remediation_description_raw": r.remediation_description_raw,
                "severity": r.severity or "medium",
                "enabled": r.enabled if r.enabled is not None else True,
                "tags": tags,
            }
        )

    content = json.dumps(export_data, indent=2, ensure_ascii=False)
    safe_name = benchmark.name.replace(" ", "_")[:60]
    filename = f"{safe_name}_phase1_rules.json"

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/{benchmark_id}/rules/import")
async def import_rules(
    benchmark_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import Phase 1 rules from a JSON file, replacing any existing rules."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are accepted")

    raw = await file.read()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    if data.get("export_type") != "phase1_rules":
        raise HTTPException(
            status_code=400,
            detail="Invalid file: expected export_type 'phase1_rules'",
        )

    rules_list = data.get("rules", [])
    if not rules_list:
        raise HTTPException(status_code=400, detail="No rules found in file")

    # Optionally update benchmark metadata from the export
    bm_meta = data.get("benchmark", {})
    if bm_meta.get("platform"):
        benchmark.platform = bm_meta["platform"]
    if bm_meta.get("platform_family"):
        benchmark.platform_family = bm_meta["platform_family"]
    if bm_meta.get("version"):
        benchmark.version = bm_meta["version"]

    # Delete existing rules (cascade deletes commands, tags, etc.)
    db.query(Rule).filter(Rule.benchmark_id == benchmark_id).delete()
    db.flush()


    created_count = 0
    for item in rules_list:
        section = item.get("section_number")
        title = item.get("title")
        if not section or not title:
            continue  # skip malformed entries

        rule = Rule(
            benchmark_id=benchmark_id,
            section_number=section,
            title=title,
            description=item.get("description"),
            rationale=item.get("rationale"),
            profile_applicability=item.get("profile_applicability"),
            assessment_type=item.get("assessment_type"),
            default_value=item.get("default_value"),
            references_json=item.get("references_json"),
            cis_controls=item.get("cis_controls"),
            audit_description_raw=item.get("audit_description_raw"),
            remediation_description_raw=item.get("remediation_description_raw"),
            severity=item.get("severity", "medium"),
            enabled=item.get("enabled", True),
        )
        db.add(rule)
        db.flush()  # get rule.id for tags

        for tag_data in item.get("tags", []):
            tag = RuleTag(
                rule_id=rule.id,
                tag_id=tag_data.get("tag_id", ""),
                source=tag_data.get("source", "imported"),
            )
            db.add(tag)

        created_count += 1

    benchmark.total_rules = created_count
    benchmark.phase1_status = "completed"
    db.commit()

    return {
        "message": f"Imported {created_count} rules",
        "rules_imported": created_count,
        "benchmark_id": benchmark_id,
    }


# ── Phase 2: Export / Import Commands ──


@router.get("/{benchmark_id}/commands/export")
def export_commands(benchmark_id: int, db: Session = Depends(get_db)):
    """Export all Phase 2 commands (with their rule context) as a downloadable JSON file."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    rules = (
        db.query(Rule)
        .filter(Rule.benchmark_id == benchmark_id)
        .order_by(Rule.section_number)
        .all()
    )

    export_data = {
        "export_type": "phase2_commands",
        "benchmark": {
            "name": benchmark.name,
            "version": benchmark.version,
            "platform": benchmark.platform,
            "platform_family": benchmark.platform_family,
        },
        "total_rules": len(rules),
        "rules": [],
    }
    for r in rules:
        cmd = r.commands
        rule_entry: dict = {
            "section_number": r.section_number,
            "title": r.title,
        }
        if cmd:
            rule_entry["command"] = {
                "audit_command": cmd.audit_command,
                "expected_output_regex": cmd.expected_output_regex,
                "expected_output_description": cmd.expected_output_description,
                "remediation_command": cmd.remediation_command,
                "remediation_description": cmd.remediation_description,
                "source": cmd.source or "imported",
                "status": cmd.status or "generated",
            }
        else:
            rule_entry["command"] = None
        export_data["rules"].append(rule_entry)

    content = json.dumps(export_data, indent=2, ensure_ascii=False)
    safe_name = benchmark.name.replace(" ", "_")[:60]
    filename = f"{safe_name}_phase2_commands.json"

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/{benchmark_id}/commands/import")
async def import_commands(
    benchmark_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import Phase 2 commands from a JSON file, matching by section_number."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are accepted")

    raw = await file.read()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    if data.get("export_type") != "phase2_commands":
        raise HTTPException(
            status_code=400,
            detail="Invalid file: expected export_type 'phase2_commands'",
        )

    rules_list = data.get("rules", [])
    if not rules_list:
        raise HTTPException(status_code=400, detail="No rules found in file")

    # Build lookup: section_number → Rule
    existing_rules = (
        db.query(Rule)
        .filter(Rule.benchmark_id == benchmark_id)
        .all()
    )
    rule_map = {r.section_number: r for r in existing_rules}

    if not rule_map:
        raise HTTPException(
            status_code=400,
            detail="No rules exist for this benchmark. Import Phase 1 rules first.",
        )


    now = datetime.now(timezone.utc)
    created = 0
    updated = 0
    skipped = 0

    for item in rules_list:
        section = item.get("section_number")
        cmd_data = item.get("command")
        if not section or not cmd_data:
            skipped += 1
            continue

        rule = rule_map.get(section)
        if not rule:
            skipped += 1
            continue

        if rule.commands:
            # Update existing command (unless protected)
            cmd = rule.commands
            if cmd.is_protected:
                skipped += 1
                continue
            cmd.audit_command = cmd_data.get("audit_command", cmd.audit_command)
            cmd.expected_output_regex = cmd_data.get("expected_output_regex", cmd.expected_output_regex)
            cmd.expected_output_description = cmd_data.get("expected_output_description", cmd.expected_output_description)
            cmd.remediation_command = cmd_data.get("remediation_command", cmd.remediation_command)
            cmd.remediation_description = cmd_data.get("remediation_description", cmd.remediation_description)
            cmd.source = cmd_data.get("source", "imported")
            cmd.status = cmd_data.get("status", "generated")
            cmd.updated_at = now
            updated += 1
        else:
            # Create new command
            cmd = RuleCommand(
                rule_id=rule.id,
                audit_command=cmd_data.get("audit_command"),
                expected_output_regex=cmd_data.get("expected_output_regex"),
                expected_output_description=cmd_data.get("expected_output_description"),
                remediation_command=cmd_data.get("remediation_command"),
                remediation_description=cmd_data.get("remediation_description"),
                source=cmd_data.get("source", "imported"),
                status=cmd_data.get("status", "generated"),
                created_at=now,
            )
            db.add(cmd)
            created += 1

    benchmark.phase2_status = "completed"
    benchmark.enrichment_stats = json.dumps(
        {"total": len(rule_map), "processed": len(rule_map)}
    )
    db.commit()

    return {
        "message": f"Imported commands: {created} created, {updated} updated, {skipped} skipped",
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "benchmark_id": benchmark_id,
    }


# ── Phase 2: Enrichment ──

@router.post("/{benchmark_id}/enrich")
async def start_enrichment(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if benchmark.phase1_status != "completed":
        raise HTTPException(status_code=400, detail="Phase 1 must be completed before enrichment")

    # Allow re-triggering from any state except active processing
    # (stale "processing" from crashed containers is handled by resetting first)
    if benchmark.phase2_status == "processing":
        # Reset stale processing state so we can re-trigger
        benchmark.phase2_status = "pending"
        db.commit()

    background_tasks.add_task(run_phase2, benchmark.id)
    return {"message": "Phase 2 enrichment started", "benchmark_id": benchmark_id}


@router.post("/{benchmark_id}/enrich/pause")
def pause_enrichment(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if benchmark.phase2_status != "processing":
        raise HTTPException(status_code=400, detail="Phase 2 is not currently running")
    request_pause(benchmark_id)
    return {"message": "Phase 2 pause requested", "benchmark_id": benchmark_id}


@router.get("/{benchmark_id}/enrich/status", response_model=EnrichStatusResponse)
def get_enrichment_status(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    stats = {}
    if benchmark.enrichment_stats:
        try:
            stats = json.loads(benchmark.enrichment_stats)
        except (json.JSONDecodeError, TypeError):
            pass

    return EnrichStatusResponse(
        total=stats.get("total", benchmark.total_rules or 0),
        processed=stats.get("processed", 0),
        status=benchmark.phase2_status or "pending",
    )


# ── Verification ──

@router.post("/{benchmark_id}/verify")
async def start_verification(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if benchmark.phase2_status != "completed":
        raise HTTPException(status_code=400, detail="Phase 2 must be completed before verification")

    background_tasks.add_task(run_verification, benchmark.id)
    return {"message": "Verification started", "benchmark_id": benchmark_id}


@router.get("/{benchmark_id}/verify/status", response_model=VerifyStatusResponse)
def get_verification_status(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    from sqlalchemy import case, func
    row = db.query(
        func.count(RuleCommand.id).label("total"),
        func.sum(case((RuleCommand.status == "verified", 1), else_=0)).label("passed"),
        func.sum(case((RuleCommand.status == "flagged", 1), else_=0)).label("failed"),
    ).join(Rule).filter(Rule.benchmark_id == benchmark_id).one()
    total = row.total or 0
    passed = int(row.passed or 0)
    failed = int(row.failed or 0)

    return VerifyStatusResponse(
        status=benchmark.verification_status or "pending",
        total=total,
        passed=passed,
        failed=failed,
    )


# ── Verification Results ──

@router.get("/{benchmark_id}/verify/results", response_model=VerificationResultsResponse)
def get_verification_results(
    benchmark_id: int,
    level: str | None = Query(None, description="Filter by check level: syntax, safety, cross_reference, regex"),
    result: str | None = Query(None, description="Filter by result: pass, fail, warn, skip"),
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    query = (
        db.query(VerificationReport)
        .join(RuleCommand, VerificationReport.rule_command_id == RuleCommand.id)
        .join(Rule, RuleCommand.rule_id == Rule.id)
        .filter(Rule.benchmark_id == benchmark_id)
    )

    if level:
        query = query.filter(VerificationReport.level == level)
    if result:
        query = query.filter(VerificationReport.result == result)

    reports = query.order_by(VerificationReport.run_at.desc()).all()
    return {
        "data": [VerificationReportResponse.model_validate(r) for r in reports],
        "total": len(reports),
        "message": "success",
    }


# ── Bulk Regenerate ──

@router.post("/{benchmark_id}/commands/bulk-regenerate")
async def bulk_regenerate_commands(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    flagged_commands = (
        db.query(RuleCommand)
        .join(Rule)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.status == "flagged",
            RuleCommand.is_protected == False,  # noqa: E712
        )
        .all()
    )

    if not flagged_commands:
        raise HTTPException(status_code=400, detail="No flagged commands to regenerate")

    rule_ids = [cmd.rule_id for cmd in flagged_commands]

    async def _bulk_regenerate(rids: list[int]) -> None:
        from backend.database import SessionLocal
        from backend.ai.benchmark_ai import regenerate_command as ai_regenerate

        db_inner = SessionLocal()
        try:
            for rid in rids:
                rule = db_inner.query(Rule).filter(Rule.id == rid).first()
                if not rule or not rule.commands:
                    continue
                cmd = rule.commands
                if cmd.is_protected or cmd.status != "flagged":
                    continue

                bm = rule.benchmark
                if not bm:
                    continue

                history: list[dict] = []
                if cmd.previous_commands:
                    try:
                        history = json.loads(cmd.previous_commands)
                    except (json.JSONDecodeError, TypeError):
                        history = []

                from datetime import datetime, timezone
                history.append({
                    "audit_command": cmd.audit_command,
                    "expected_output_regex": cmd.expected_output_regex,
                    "flag_reason": cmd.flag_reason,
                    "source": cmd.source,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                try:
                    result = await ai_regenerate(
                        section_number=rule.section_number,
                        title=rule.title,
                        platform=bm.platform,
                        platform_family=bm.platform_family,
                        assessment_type=rule.assessment_type,
                        audit_description_raw=rule.audit_description_raw,
                        remediation_description_raw=rule.remediation_description_raw,
                        current_audit_command=cmd.audit_command,
                        current_expected_output_regex=cmd.expected_output_regex,
                        flag_reason=cmd.flag_reason or "Flagged for regeneration",
                        flag_error_output=cmd.flag_error_output,
                        previous_commands=history,
                    )
                except Exception:
                    logger.warning("Failed to regenerate command for rule %s", rid)
                    continue

                now = datetime.now(timezone.utc)
                cmd.audit_command = result.get("audit_command", cmd.audit_command)
                cmd.expected_output_regex = result.get("expected_output_regex", cmd.expected_output_regex)
                cmd.expected_output_description = result.get("expected_output_description", cmd.expected_output_description)
                cmd.remediation_command = result.get("remediation_command", cmd.remediation_command)
                cmd.remediation_description = result.get("remediation_description", cmd.remediation_description)
                cmd.source = "llm_regenerated"
                cmd.status = "generated"
                cmd.flag_reason = None
                cmd.flag_error_output = None
                cmd.flagged_at = None
                cmd.regeneration_count = (cmd.regeneration_count or 0) + 1
                cmd.last_regenerated_at = now
                cmd.previous_commands = json.dumps(history)
                cmd.updated_at = now
                db_inner.commit()
        except Exception:
            logger.exception("Bulk regeneration failed")
            db_inner.rollback()
        finally:
            db_inner.close()

    background_tasks.add_task(_bulk_regenerate, rule_ids)
    return {
        "message": f"Bulk regeneration started for {len(rule_ids)} commands",
        "benchmark_id": benchmark_id,
        "count": len(rule_ids),
    }


# ── Bulk Accept ──

@router.post("/{benchmark_id}/verify/bulk-accept")
def bulk_accept_commands(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    now = datetime.now(timezone.utc)

    updated = (
        db.query(RuleCommand)
        .join(Rule)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.status.in_(["generated", "pending_review"]),
            RuleCommand.is_protected == False,  # noqa: E712
        )
        .all()
    )

    count = 0
    for cmd in updated:
        cmd.status = "verified"
        cmd.verified_at = now
        cmd.verification_notes = "Bulk accepted by auditor"
        count += 1

    db.commit()
    return {"message": f"Accepted {count} commands", "count": count}


# ── Override Gate ──

@router.post("/{benchmark_id}/verify/override")
def override_verification_gate(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    benchmark.is_ready = True
    if benchmark.verification_status == "completed_with_issues":
        benchmark.verification_status = "overridden"
    db.commit()
    return {"message": "Benchmark marked as ready (verification overridden)", "benchmark_id": benchmark_id}


# ── Bulk Protect ──

@router.post("/{benchmark_id}/commands/bulk-protect")
def bulk_protect_commands(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    now = datetime.now(timezone.utc)

    verified_commands = (
        db.query(RuleCommand)
        .join(Rule)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.status == "verified",
            RuleCommand.is_protected.is_(False),
        )
        .all()
    )

    count = 0
    for cmd in verified_commands:
        cmd.is_protected = True
        cmd.protected_at = now
        cmd.protection_reason = "Bulk protected by auditor"
        cmd.updated_at = now
        count += 1

    db.commit()
    return {"message": f"Protected {count} commands", "protected_count": count}


# ── Phase 3: Validate & Correct (optional) ──

@router.post("/{benchmark_id}/validate")
async def start_validation(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start Phase 3 validation — optional LLM review of generated commands."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if benchmark.phase2_status != "completed":
        raise HTTPException(status_code=400, detail="Phase 2 must be completed before validation")

    # Allow re-triggering from any state except active processing
    if benchmark.phase3_status == "processing":
        benchmark.phase3_status = "pending"
        db.commit()

    background_tasks.add_task(run_phase3, benchmark.id)
    return {"message": "Phase 3 validation started", "benchmark_id": benchmark_id}


@router.post("/{benchmark_id}/validate/pause")
def pause_validation(benchmark_id: int, db: Session = Depends(get_db)):
    """Pause an in-progress Phase 3 validation."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if benchmark.phase3_status != "processing":
        raise HTTPException(status_code=400, detail="Phase 3 is not currently running")
    phase3_request_pause(benchmark_id)
    return {"message": "Phase 3 pause requested", "benchmark_id": benchmark_id}


@router.get("/{benchmark_id}/validate/status", response_model=ValidateStatusResponse)
def get_validation_status(benchmark_id: int, db: Session = Depends(get_db)):
    """Get Phase 3 validation progress."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    stats: dict = {}
    if benchmark.phase3_stats:
        try:
            stats = json.loads(benchmark.phase3_stats)
        except (json.JSONDecodeError, TypeError):
            pass

    return ValidateStatusResponse(
        status=benchmark.phase3_status or "not_started",
        total=stats.get("total", 0),
        processed=stats.get("processed", 0),
        validated=stats.get("validated", 0),
        corrected=stats.get("corrected", 0),
        flagged=stats.get("flagged", 0),
    )


@router.get("/{benchmark_id}/validate/results", response_model=ValidationResultsResponse)
def get_validation_results(
    benchmark_id: int,
    status_filter: str | None = Query(None, description="Filter by: corrected, flagged, validated"),
    db: Session = Depends(get_db),
):
    """Get Phase 3 validation results with corrections."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    query = (
        db.query(RuleCommand, Rule)
        .join(Rule, RuleCommand.rule_id == Rule.id)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.validation_status.isnot(None),
        )
    )
    if status_filter:
        query = query.filter(RuleCommand.validation_status == status_filter)

    rows = query.order_by(Rule.section_number).all()

    items: list[ValidationResultItem] = []
    for cmd, rule in rows:
        corrections: list[ValidationCorrection] = []
        if cmd.validation_corrections:
            try:
                raw = json.loads(cmd.validation_corrections)
                corrections = [ValidationCorrection(**c) for c in raw]
            except (json.JSONDecodeError, TypeError):
                pass

        items.append(ValidationResultItem(
            rule_command_id=cmd.id,
            rule_id=rule.id,
            section_number=rule.section_number or "",
            title=rule.title or "",
            validation_status=cmd.validation_status,
            validation_confidence=cmd.validation_confidence,
            corrections=corrections,
            notes=cmd.validation_notes,
            audit_command=cmd.audit_command,
            expected_output_regex=cmd.expected_output_regex,
        ))

    return ValidationResultsResponse(
        data=items,
        total=len(items),
    )


@router.post("/{benchmark_id}/validate/apply/{rule_command_id}")
def apply_validation_correction(
    benchmark_id: int,
    rule_command_id: int,
    db: Session = Depends(get_db),
):
    """Apply LLM-suggested corrections for a specific rule command."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    try:
        cmd = phase3_apply(db, rule_command_id)
        return {"message": "Corrections applied", "rule_command_id": cmd.id, "status": cmd.validation_status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{benchmark_id}/validate/dismiss/{rule_command_id}")
def dismiss_validation_correction(
    benchmark_id: int,
    rule_command_id: int,
    db: Session = Depends(get_db),
):
    """Dismiss LLM corrections for a specific rule command (keep original)."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    try:
        cmd = phase3_dismiss(db, rule_command_id)
        return {"message": "Corrections dismissed", "rule_command_id": cmd.id, "status": cmd.validation_status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{benchmark_id}/validate/bulk-apply")
def bulk_apply_corrections(benchmark_id: int, db: Session = Depends(get_db)):
    """Apply all high-confidence corrections at once."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    commands = (
        db.query(RuleCommand)
        .join(Rule)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.validation_status == "corrected",
            RuleCommand.validation_confidence == "high",
            RuleCommand.validation_corrections.isnot(None),
        )
        .all()
    )

    count = 0
    for cmd in commands:
        try:
            phase3_apply(db, cmd.id)
            count += 1
        except (ValueError, Exception):
            continue

    return {"message": f"Applied corrections to {count} commands", "count": count}


@router.post("/{benchmark_id}/validate/bulk-dismiss")
def bulk_dismiss_corrections(benchmark_id: int, db: Session = Depends(get_db)):
    """Dismiss all pending corrections."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    now = datetime.now(timezone.utc)
    commands = (
        db.query(RuleCommand)
        .join(Rule)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.validation_status.in_(["corrected", "flagged"]),
        )
        .all()
    )

    count = 0
    for cmd in commands:
        cmd.validation_status = "dismissed"
        cmd.updated_at = now
        count += 1

    db.commit()
    return {"message": f"Dismissed corrections for {count} commands", "count": count}

