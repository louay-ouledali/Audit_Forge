from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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

    return ScanStatusResponse(
        scan_id=scan.id,
        status=scan.status,
        progress=scan.total_rules_checked or 0,
        total=scan.total_rules_checked or 0,
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
