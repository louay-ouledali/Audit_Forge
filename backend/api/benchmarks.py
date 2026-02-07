from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from backend.config import PROJECT_ROOT
from backend.core.phase1_parser import compute_pdf_hash, run_phase1
from backend.core.phase2_enricher import is_paused, request_pause, run_phase2
from backend.core.verification_engine import run_verification
from backend.database import get_db
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.verification_report import VerificationReport
from backend.schemas.benchmark import (
    BenchmarkDetailEnvelope,
    BenchmarkImportResponse,
    BenchmarkListResponse,
    BenchmarkResponse,
    BenchmarkStatusResponse,
    EnrichStatusResponse,
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
    if benchmark.phase2_status == "processing":
        raise HTTPException(status_code=400, detail="Phase 2 is already running")

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

    from datetime import datetime, timezone
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

    from datetime import datetime, timezone
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
