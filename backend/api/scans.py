from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.core.scan_executor import (
    cancel_scan,
    execute_network_scan,
    get_scan_progress,
)
from backend.core.script_generator import generate_script_package, preview_script_rules
from backend.database import SessionLocal, get_db
from backend.models.benchmark import Benchmark
from backend.models.scan import Scan
from backend.models.target import Target
from backend.schemas.scan import (
    GenerateScriptRequest,
    NetworkScanRequest,
    NetworkScanResponse,
    ScanCancelResponse,
    ScanStatusResponse,
    ScriptPreviewResponse,
    ScriptPreviewRule,
)

router = APIRouter(prefix="/scans", tags=["scans"])


# ── Script generation (existing) ─────────────────────────────


@router.post("/generate-script")
def generate_script(payload: GenerateScriptRequest, db: Session = Depends(get_db)):
    """Generate an audit script package (ZIP download)."""

    benchmark = db.query(Benchmark).filter(Benchmark.id == payload.benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    filter_kwargs = {
        "selected_rule_ids": payload.selected_rule_ids,
        "category_filter": payload.category_filter,
        "severity_filter": payload.severity_filter,
        "profile_filter": payload.profile_filter,
        "preset_id": payload.preset_id,
    }

    try:
        zip_bytes, zip_filename = generate_script_package(
            db,
            benchmark_id=payload.benchmark_id,
            **filter_kwargs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


@router.post("/generate-script/preview", response_model=ScriptPreviewResponse)
def preview_script(payload: GenerateScriptRequest, db: Session = Depends(get_db)):
    """Preview which rules would be included in the generated script."""

    benchmark = db.query(Benchmark).filter(Benchmark.id == payload.benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    filter_kwargs = {
        "selected_rule_ids": payload.selected_rule_ids,
        "category_filter": payload.category_filter,
        "severity_filter": payload.severity_filter,
        "profile_filter": payload.profile_filter,
        "preset_id": payload.preset_id,
    }

    rules = preview_script_rules(db, benchmark_id=payload.benchmark_id, **filter_kwargs)

    return ScriptPreviewResponse(
        total_rules=len(rules),
        rules=[ScriptPreviewRule(**r) for r in rules],
    )


# ── Network scan endpoints ────────────────────────────────────


def _run_scan_in_background(
    scan_id: int,
    target_id: int,
    benchmark_id: int,
    selected_rule_ids: list[int] | None,
    category_filter: list[str] | None,
    severity_filter: list[str] | None,
    profile_filter: str | None,
    preset_id: int | None,
) -> None:
    """Wrapper that runs the async scan executor inside a new event loop.

    FastAPI ``BackgroundTasks`` run in a thread-pool, so we need our own
    loop to drive the async connector calls.
    """
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            execute_network_scan(
                db_factory=SessionLocal,
                scan_id=scan_id,
                target_id=target_id,
                benchmark_id=benchmark_id,
                selected_rule_ids=selected_rule_ids,
                category_filter=category_filter,
                severity_filter=severity_filter,
                profile_filter=profile_filter,
                preset_id=preset_id,
            )
        )
    finally:
        loop.close()


@router.post("/network", response_model=NetworkScanResponse)
def start_network_scan(
    payload: NetworkScanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start a network scan against a target."""

    # Validate target
    target = db.query(Target).filter(Target.id == payload.target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    # Validate benchmark
    benchmark = db.query(Benchmark).filter(Benchmark.id == payload.benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    # Create scan record
    scan = Scan(
        target_id=payload.target_id,
        benchmark_id=payload.benchmark_id,
        scan_mode="network",
        preset_id=payload.preset_id,
        status="pending",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    # Launch background task
    background_tasks.add_task(
        _run_scan_in_background,
        scan_id=scan.id,
        target_id=payload.target_id,
        benchmark_id=payload.benchmark_id,
        selected_rule_ids=payload.selected_rule_ids,
        category_filter=payload.category_filter,
        severity_filter=payload.severity_filter,
        profile_filter=payload.profile_filter,
        preset_id=payload.preset_id,
    )

    return NetworkScanResponse(scan_id=scan.id, status="running")


@router.get("/{scan_id}/status", response_model=ScanStatusResponse)
def get_scan_status(scan_id: int, db: Session = Depends(get_db)):
    """Return current status and progress for a scan."""

    # Check in-memory progress first (active scan)
    progress = get_scan_progress(scan_id)
    if progress:
        return ScanStatusResponse(**progress)

    # Fallback to database record (completed / failed scan)
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    total_checked = scan.total_rules_checked or 0
    return ScanStatusResponse(
        scan_id=scan.id,
        status=scan.status,
        progress=total_checked,
        total=scan.total_rules or total_checked,
        current_rule="",
        passed=scan.passed or 0,
        failed=scan.failed or 0,
        errors=scan.errors or 0,
        compliance_percentage=scan.compliance_percentage or 0.0,
    )


@router.post("/{scan_id}/cancel", response_model=ScanCancelResponse)
def cancel_running_scan(scan_id: int, db: Session = Depends(get_db)):
    """Cancel a running scan gracefully."""

    if cancel_scan(scan_id):
        return ScanCancelResponse(
            scan_id=scan_id,
            status="cancelling",
            message="Scan cancellation requested",
        )

    # Not in active progress — check DB
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Scan is already {scan.status}",
        )

    # Mark as cancelled in DB directly
    scan.status = "cancelled"
    db.commit()
    return ScanCancelResponse(
        scan_id=scan_id,
        status="cancelled",
        message="Scan cancelled",
    )


# ── Scan CRUD ─────────────────────────────────────────────────


@router.get("", response_model=None)
def list_scans(
    mission_id: int | None = None,
    target_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """List all scans with optional filters."""
    from backend.models.target import Target as TargetModel

    query = db.query(Scan)
    if target_id:
        query = query.filter(Scan.target_id == target_id)
    if mission_id:
        subq = db.query(TargetModel.id).filter(TargetModel.mission_id == mission_id).subquery()
        query = query.filter(Scan.target_id.in_(subq))
    if status:
        query = query.filter(Scan.status == status)

    scans = query.order_by(Scan.created_at.desc()).all()
    return {
        "data": [
            {
                "id": s.id,
                "target_id": s.target_id,
                "benchmark_id": s.benchmark_id,
                "scan_mode": s.scan_mode,
                "status": s.status,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "results_imported_at": s.results_imported_at.isoformat() if s.results_imported_at else None,
                "total_rules": s.total_rules or 0,
                "total_rules_checked": s.total_rules_checked or 0,
                "passed": s.passed or 0,
                "failed": s.failed or 0,
                "errors": s.errors or 0,
                "not_applicable": s.not_applicable or 0,
                "manual_review": s.manual_review or 0,
                "compliance_percentage": s.compliance_percentage,
                "notes": s.notes,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in scans
        ],
        "total": len(scans),
    }


@router.post("/import")
async def import_with_new_scan(
    target_id: int = Form(...),
    benchmark_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Create a new scan and import results in one step."""
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    scan = Scan(
        target_id=target_id,
        benchmark_id=benchmark_id,
        scan_mode="import",
        status="pending",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    content = await _extract_result_content(file)

    try:
        from backend.core.result_importer import detect_format_and_import, finalize_scan_stats
        stats = detect_format_and_import(content, scan.id, benchmark_id, db)
        finalize_scan_stats(scan, stats, db)
    except ValueError as exc:
        db.delete(scan)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc))

    return {**stats, "scan_id": scan.id}


@router.get("/{scan_id}")
def get_scan_detail(scan_id: int, db: Session = Depends(get_db)):
    """Get a single scan with aggregate stats."""
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    return {
        "data": {
            "id": scan.id,
            "target_id": scan.target_id,
            "benchmark_id": scan.benchmark_id,
            "scan_mode": scan.scan_mode,
            "status": scan.status,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
            "results_imported_at": scan.results_imported_at.isoformat() if scan.results_imported_at else None,
            "total_rules": scan.total_rules or 0,
            "total_rules_checked": scan.total_rules_checked or 0,
            "passed": scan.passed or 0,
            "failed": scan.failed or 0,
            "errors": scan.errors or 0,
            "not_applicable": scan.not_applicable or 0,
            "manual_review": scan.manual_review or 0,
            "compliance_percentage": scan.compliance_percentage,
            "notes": scan.notes,
            "created_at": scan.created_at.isoformat() if scan.created_at else None,
        }
    }


@router.delete("/{scan_id}")
def delete_scan(scan_id: int, db: Session = Depends(get_db)):
    """Delete a scan and all its findings."""
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    db.delete(scan)
    db.commit()
    return {"message": "Scan deleted", "scan_id": scan_id}


# ── Findings for a scan ──────────────────────────────────────


@router.get("/{scan_id}/findings")
def list_scan_findings(
    scan_id: int,
    status: str | None = None,
    severity: str | None = None,
    db: Session = Depends(get_db),
):
    """List findings for a specific scan with optional filters."""
    from backend.models.finding import Finding
    from backend.models.rule import Rule

    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    query = db.query(Finding).filter(Finding.scan_id == scan_id)
    if status:
        query = query.filter(Finding.status == status)
    if severity:
        query = query.filter(Finding.severity == severity)

    findings = query.order_by(Finding.id).all()
    result = []
    for f in findings:
        rule = db.query(Rule).filter(Rule.id == f.rule_id).first()
        result.append({
            "id": f.id,
            "scan_id": f.scan_id,
            "rule_id": f.rule_id,
            "status": f.status,
            "actual_output": f.actual_output,
            "expected_output": f.expected_output,
            "severity": f.severity,
            "ai_advice": f.ai_advice,
            "ai_advice_generated_at": f.ai_advice_generated_at.isoformat() if f.ai_advice_generated_at else None,
            "auditor_notes": f.auditor_notes,
            "auditor_override": f.auditor_override,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "section_number": rule.section_number if rule else None,
            "rule_title": rule.title if rule else None,
        })
    return {"data": result, "total": len(result)}


# ── Result import ─────────────────────────────────────────────


@router.post("/{scan_id}/import-results")
async def import_results(
    scan_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import results for an existing scan.

    Accepts:
    - JSON file (audit_results.json)
    - TXT file (marker-based output)
    - ZIP file containing either of the above
    """
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    content = await _extract_result_content(file)

    try:
        from backend.core.result_importer import detect_format_and_import, finalize_scan_stats
        stats = detect_format_and_import(content, scan_id, scan.benchmark_id, db)
        finalize_scan_stats(scan, stats, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return stats


MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_DECOMPRESSED_SIZE = 200 * 1024 * 1024  # 200 MB – guard against zip bombs


async def _extract_result_content(file: UploadFile) -> str:
    """Read uploaded file content. If ZIP, extract the first suitable file."""
    raw = await file.read()

    if len(raw) > MAX_UPLOAD_SIZE:
        raise ValueError(f"File too large ({len(raw)} bytes). Maximum is {MAX_UPLOAD_SIZE} bytes.")

    filename = file.filename or ""

    if filename.endswith(".zip") or raw[:4] == b'PK\x03\x04':
        import zipfile
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                target_file = None
                for name in names:
                    if name.endswith("audit_results.json"):
                        target_file = name
                        break
                if not target_file:
                    for name in names:
                        if name.endswith(".json"):
                            target_file = name
                            break
                if not target_file:
                    for name in names:
                        if name.endswith(".txt"):
                            target_file = name
                            break
                if not target_file and names:
                    target_file = names[0]
                if not target_file:
                    raise ValueError("ZIP file is empty")

                info = zf.getinfo(target_file)
                if info.file_size > MAX_DECOMPRESSED_SIZE:
                    raise ValueError(
                        f"Decompressed file too large ({info.file_size} bytes). "
                        f"Maximum is {MAX_DECOMPRESSED_SIZE} bytes."
                    )

                return zf.read(target_file).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            raise ValueError("Invalid ZIP file")

    return raw.decode("utf-8", errors="replace")
