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
from backend.schemas.benchmark import (
    BenchmarkDetailEnvelope,
    BenchmarkImportResponse,
    BenchmarkListResponse,
    BenchmarkResponse,
    BenchmarkStatusResponse,
    EnrichStatusResponse,
    VerifyStatusResponse,
)

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
