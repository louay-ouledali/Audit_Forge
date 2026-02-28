from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.network_discovery import (
    cleanup_discovery,
    discover_network,
    get_discovery_progress,
)
from backend.core.scan_executor import (
    cancel_scan,
    execute_network_scan,
    get_scan_progress,
)
from backend.core.script_generator import generate_script_package, preview_script_rules
from backend.database import SessionLocal, get_db
from backend.models.benchmark import Benchmark
from backend.models.mission_target import MissionTarget
from backend.models.scan import Scan
from backend.models.scan_batch import ScanBatch, ScanBatchItem
from backend.models.target import Target
from backend.schemas.scan import (
    GenerateScriptRequest,
    NetworkScanRequest,
    NetworkScanResponse,
    ScanBatchItemResponse,
    ScanBatchRequest,
    ScanBatchResponse,
    ScanBatchStatusResponse,
    ScanCancelResponse,
    ScanStatusResponse,
    ScriptPreviewResponse,
    ScriptPreviewRule,
)

router = APIRouter(prefix="/scans", tags=["scans"])
logger = logging.getLogger("auditforge.api.scans")


# ── Network Discovery ────────────────────────────────────────


class DiscoveryRequest(BaseModel):
    subnet: str  # CIDR, range, or single IP
    mission_id: int | None = None  # optional — marks already-assigned targets


class DiscoveryResponse(BaseModel):
    discovery_id: str
    status: str


@router.post("/discover", response_model=DiscoveryResponse)
async def start_discovery(payload: DiscoveryRequest):
    """Start a network discovery scan on the given subnet."""
    discovery_id = str(uuid.uuid4())[:8]

    async def _run_discovery():
        try:
            await discover_network(payload.subnet, discovery_id=discovery_id)
        except Exception as exc:
            from backend.core.network_discovery import _discovery_progress
            _discovery_progress[discovery_id] = {
                "id": discovery_id,
                "status": "failed",
                "error": str(exc),
                "total": 0,
                "scanned": 0,
                "found": 0,
            }

    asyncio.ensure_future(_run_discovery())
    return DiscoveryResponse(discovery_id=discovery_id, status="running")


@router.get("/discover/{discovery_id}/status")
async def get_discovery_status(discovery_id: str):
    """Return current progress/results for a discovery scan."""
    progress = get_discovery_progress(discovery_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Discovery not found")
    return progress


@router.get("/discover/{discovery_id}/results")
async def get_discovery_results(discovery_id: str):
    """Return the full list of discovered hosts."""
    progress = get_discovery_progress(discovery_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Discovery not found")
    if progress.get("status") != "completed":
        return {"status": progress.get("status"), "hosts": []}

    # Re-run to get results (they're returned, not stored separately)
    # For simplicity, store results in progress dict
    return {"status": "completed", "hosts": progress.get("hosts", [])}


@router.post("/discover/scan")
async def discover_and_return(
    payload: DiscoveryRequest,
    db: Session = Depends(get_db),
):
    """Run discovery synchronously and return results immediately.

    Use this for small subnets (single IP or /28 and smaller).
    For larger subnets, use the async POST /discover endpoint.
    """
    try:
        hosts = await discover_network(payload.subnet)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Enrich with existing target info and benchmark suggestions
    enriched = _enrich_discovered_hosts(hosts, payload.mission_id, db)
    return {"hosts": enriched, "total_scanned": len(enriched)}


# ── Discovery enrichment helper ──────────────────────────────


def _enrich_discovered_hosts(
    hosts: list[dict],
    mission_id: int | None,
    db: Session,
) -> list[dict]:
    """Add already_added, existing_target_id, and suggested_benchmark to discovered hosts."""
    # Build a lookup of existing targets keyed by IP
    all_targets = db.query(Target).all()
    ip_to_target: dict[str, Target] = {}
    for t in all_targets:
        if t.ip_address:
            ip_to_target[t.ip_address] = t

    # If mission_id is given, get assigned target IDs
    assigned_ids: set[int] = set()
    if mission_id:
        links = db.query(MissionTarget).filter(MissionTarget.mission_id == mission_id).all()
        assigned_ids = {lnk.target_id for lnk in links}

    # Pre-fetch all active benchmarks for suggestion matching
    benchmarks = db.query(Benchmark).filter(Benchmark.status == "active").all()

    enriched = []
    for host in hosts:
        ip = host.get("ip", "")
        os_guess = (host.get("os_guess", "") or "").lower()

        existing = ip_to_target.get(ip)
        host["already_added"] = existing is not None
        host["existing_target_id"] = existing.id if existing else None
        host["already_assigned"] = existing.id in assigned_ids if existing else False

        # Suggest benchmark based on OS guess
        suggested_name = None
        suggested_id = None
        for bm in benchmarks:
            bm_name_lower = (bm.name or "").lower()
            bm_platform_lower = (bm.platform or "").lower()
            if os_guess and (os_guess in bm_name_lower or os_guess in bm_platform_lower):
                suggested_name = f"{bm.name} v{bm.version}" if bm.version else bm.name
                suggested_id = bm.id
                break
        host["suggested_benchmark"] = suggested_name
        host["suggested_benchmark_id"] = suggested_id

        enriched.append(host)

    return enriched


# ── Script generation (existing) ─────────────────────────────


@router.post("/generate-script")
def generate_script(payload: GenerateScriptRequest, db: Session = Depends(get_db)):
    """Generate an audit script package (ZIP download).

    When ``target_id`` is provided, the script is tailored:
    - Filename includes the target hostname
    - Network/database targets get an error (USB not supported)
    """

    benchmark = db.query(Benchmark).filter(Benchmark.id == payload.benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    # Platform validation when target_id is supplied
    target = None
    if payload.target_id:
        target = db.query(Target).filter(Target.id == payload.target_id).first()
        if target:
            ttype = (target.target_type or "").lower()
            unsupported = ("cisco_ios", "juniper", "fortinet", "palo_alto", "arista",
                           "hp_procurve", "postgresql", "oracle", "mssql")
            if ttype in unsupported:
                raise HTTPException(
                    status_code=400,
                    detail=f"USB script export is not supported for {ttype} targets. "
                           f"Use network scanning instead.",
                )

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

    # Customize filename if target provided
    if target and target.hostname:
        base_name = zip_filename.rsplit(".", 1)[0]
        zip_filename = f"{base_name}_{target.hostname}.zip"

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
        mission_id=payload.mission_id,
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
        error_message=scan.notes if scan.status == "failed" else None,
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
    from backend.models.mission import Mission as MissionModel
    from backend.models.client import Client as ClientModel

    query = db.query(Scan)
    if target_id:
        query = query.filter(Scan.target_id == target_id)
    if mission_id:
        # Scans now have direct mission_id
        query = query.filter(Scan.mission_id == mission_id)
    if status:
        query = query.filter(Scan.status == status)

    scans = query.order_by(Scan.created_at.desc()).all()

    # Pre-fetch related names for enrichment
    target_ids = {s.target_id for s in scans if s.target_id}
    benchmark_ids = {s.benchmark_id for s in scans if s.benchmark_id}

    targets_map: dict[int, TargetModel] = {}
    missions_map: dict[int, MissionModel] = {}
    clients_map: dict[int, ClientModel] = {}
    benchmarks_map: dict[int, Benchmark] = {}

    if target_ids:
        for t in db.query(TargetModel).filter(TargetModel.id.in_(target_ids)).all():
            targets_map[t.id] = t
        # Get clients from targets (targets now belong to clients)
        client_ids = {t.client_id for t in targets_map.values() if t.client_id}
        if client_ids:
            for c in db.query(ClientModel).filter(ClientModel.id.in_(client_ids)).all():
                clients_map[c.id] = c

    # Get missions from scans' direct mission_id
    mission_ids_set = {s.mission_id for s in scans if s.mission_id}
    if mission_ids_set:
        for m in db.query(MissionModel).filter(MissionModel.id.in_(mission_ids_set)).all():
            missions_map[m.id] = m

    if benchmark_ids:
        for b in db.query(Benchmark).filter(Benchmark.id.in_(benchmark_ids)).all():
            benchmarks_map[b.id] = b

    result = []
    for s in scans:
        tgt = targets_map.get(s.target_id) if s.target_id else None
        bm = benchmarks_map.get(s.benchmark_id) if s.benchmark_id else None
        msn = missions_map.get(s.mission_id) if s.mission_id else None
        cli = clients_map.get(tgt.client_id) if tgt and tgt.client_id else None

        result.append({
            "id": s.id,
            "target_id": s.target_id,
            "benchmark_id": s.benchmark_id,
            "mission_id": s.mission_id,
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
            # Enriched naming fields
            "benchmark_name": bm.name if bm else None,
            "benchmark_version": bm.version if bm else None,
            "target_hostname": tgt.hostname if tgt else None,
            "target_ip": tgt.ip_address if tgt else None,
            "mission_name": msn.name if msn else None,
            "client_name": cli.name if cli else None,
        })

    return {"data": result, "total": len(result)}


@router.post("/import")
async def import_with_new_scan(
    target_id: int = Form(...),
    benchmark_id: int = Form(...),
    mission_id: int | None = Form(None),
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
        mission_id=mission_id,
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
            "mission_id": scan.mission_id,
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

                data = zf.read(target_file)
                if len(data) > MAX_DECOMPRESSED_SIZE:
                    raise ValueError(
                        f"Decompressed file too large ({len(data)} bytes). "
                        f"Maximum is {MAX_DECOMPRESSED_SIZE} bytes."
                    )

                return data.decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            raise ValueError("Invalid ZIP file")

    return raw.decode("utf-8", errors="replace")


# ── Scan Batch ("Scan All") ──────────────────────────────────

# In-memory progress tracker for batch scans
_batch_progress: dict[int, dict] = {}


def _resolve_benchmark(
    target: Target,
    overrides: dict[str, int] | None,
    db: Session,
) -> Benchmark | None:
    """Determine which benchmark to use for a target during batch scan."""
    # 1. Check explicit override
    if overrides:
        override_id = overrides.get(str(target.id))
        if override_id:
            return db.query(Benchmark).filter(Benchmark.id == override_id).first()

    # 2. Use target's default benchmark
    if target.default_benchmark_id:
        return db.query(Benchmark).filter(Benchmark.id == target.default_benchmark_id).first()

    # 3. Best-effort auto-match by platform_family
    ttype = (target.target_type or "").lower().strip()
    family_map = {
        "windows": "windows", "linux": "linux",
        "cisco_ios": "network", "juniper": "network", "fortinet": "network",
        "palo_alto": "network", "arista": "network", "hp_procurve": "network",
        "postgresql": "database", "oracle": "database", "mssql": "database",
    }
    family = family_map.get(ttype)
    if family:
        bm = (
            db.query(Benchmark)
            .filter(Benchmark.platform_family == family, Benchmark.status == "active", Benchmark.is_ready.is_(True))
            .first()
        )
        if bm:
            return bm

    return None


def _target_has_credentials(target: Target) -> bool:
    """Check whether a target has any credentials configured."""
    return bool(
        target.ssh_password_encrypted
        or target.ssh_key_path
        or target.db_connection_string_encrypted
    )


@router.post("/batch", response_model=ScanBatchResponse)
def start_scan_batch(
    payload: ScanBatchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Launch a batch scan ("Scan All") for a mission."""
    from backend.models.mission import Mission

    mission = db.query(Mission).filter(Mission.id == payload.mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    # Resolve target list
    if payload.target_ids:
        targets = db.query(Target).filter(Target.id.in_(payload.target_ids)).all()
    else:
        # All targets assigned to this mission
        mt_ids = [
            mt.target_id
            for mt in db.query(MissionTarget).filter(MissionTarget.mission_id == payload.mission_id).all()
        ]
        targets = db.query(Target).filter(Target.id.in_(mt_ids)).all() if mt_ids else []

    if not targets:
        raise HTTPException(status_code=400, detail="No targets to scan")

    # Pre-fetch benchmark map
    benchmarks_map: dict[int, Benchmark] = {}

    # Create batch record
    batch = ScanBatch(
        mission_id=payload.mission_id,
        status="pending",
        total_targets=len(targets),
        concurrency=payload.concurrency,
    )
    db.add(batch)
    db.flush()  # get batch.id

    items: list[ScanBatchItem] = []
    scannable_count = 0
    skipped_count = 0

    for target in targets:
        bm = _resolve_benchmark(target, payload.benchmark_overrides, db)
        has_creds = _target_has_credentials(target)

        # Determine if scannable
        skip_reason = None
        if not has_creds:
            skip_reason = "no_credentials"
        elif not bm:
            skip_reason = "no_benchmark"

        if skip_reason and not payload.skip_untestable:
            raise HTTPException(
                status_code=400,
                detail=f"Target '{target.hostname or target.ip_address}' cannot be scanned: {skip_reason}. "
                       f"Set skip_untestable=true to skip such targets.",
            )

        status = "skipped" if skip_reason else "pending"
        item = ScanBatchItem(
            batch_id=batch.id,
            target_id=target.id,
            benchmark_id=bm.id if bm else None,
            status=status,
            skip_reason=skip_reason,
        )
        db.add(item)
        items.append(item)

        if bm:
            benchmarks_map[bm.id] = bm
        if skip_reason:
            skipped_count += 1
        else:
            scannable_count += 1

    batch.skipped_targets = skipped_count
    db.commit()
    db.refresh(batch)
    for item in items:
        db.refresh(item)

    # Build response items
    resp_items = []
    for item in items:
        tgt = next((t for t in targets if t.id == item.target_id), None)
        bm = benchmarks_map.get(item.benchmark_id) if item.benchmark_id else None
        resp_items.append(ScanBatchItemResponse(
            id=item.id,
            target_id=item.target_id,
            target_hostname=tgt.hostname if tgt else None,
            target_ip=tgt.ip_address if tgt else None,
            benchmark_id=item.benchmark_id,
            benchmark_name=(f"{bm.name} v{bm.version}" if bm and bm.version else bm.name) if bm else None,
            scan_id=item.scan_id,
            status=item.status,
            skip_reason=item.skip_reason,
            error_message=item.error_message,
        ))

    # Launch background batch execution
    if scannable_count > 0:
        background_tasks.add_task(
            _run_batch_in_background,
            batch_id=batch.id,
            mission_id=payload.mission_id,
            concurrency=payload.concurrency,
        )

    return ScanBatchResponse(
        batch_id=batch.id,
        status="running" if scannable_count > 0 else "completed",
        total_targets=len(targets),
        scannable=scannable_count,
        skipped=skipped_count,
        items=resp_items,
    )


def _run_batch_in_background(
    batch_id: int,
    mission_id: int,
    concurrency: int = 3,
) -> None:
    """Run the batch scan in a thread-pool background task."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            _execute_scan_batch(batch_id, mission_id, concurrency)
        )
    finally:
        loop.close()


async def _execute_scan_batch(
    batch_id: int,
    mission_id: int,
    concurrency: int = 3,
) -> None:
    """Process scan batch items with bounded concurrency."""
    db: Session = SessionLocal()
    try:
        batch = db.query(ScanBatch).filter(ScanBatch.id == batch_id).first()
        if not batch:
            return

        batch.status = "running"
        db.commit()

        # Get all pending items
        items = (
            db.query(ScanBatchItem)
            .filter(ScanBatchItem.batch_id == batch_id, ScanBatchItem.status == "pending")
            .all()
        )

        semaphore = asyncio.Semaphore(concurrency)

        async def scan_one(item_id: int, target_id: int, benchmark_id: int) -> None:
            async with semaphore:
                inner_db: Session = SessionLocal()
                try:
                    item = inner_db.query(ScanBatchItem).filter(ScanBatchItem.id == item_id).first()
                    if not item or item.status != "pending":
                        return

                    item.status = "running"
                    inner_db.commit()

                    # Create scan row
                    scan = Scan(
                        target_id=target_id,
                        benchmark_id=benchmark_id,
                        mission_id=mission_id,
                        scan_mode="network",
                        status="pending",
                    )
                    inner_db.add(scan)
                    inner_db.commit()
                    inner_db.refresh(scan)

                    item.scan_id = scan.id
                    inner_db.commit()

                    # Execute scan
                    try:
                        await execute_network_scan(
                            db_factory=SessionLocal,
                            scan_id=scan.id,
                            target_id=target_id,
                            benchmark_id=benchmark_id,
                        )
                        # Reload to get final status
                        inner_db.refresh(scan)
                        if scan.status == "completed":
                            item.status = "completed"
                        else:
                            item.status = "failed"
                            item.error_message = scan.notes
                    except Exception as exc:
                        item.status = "failed"
                        item.error_message = str(exc)
                        logger.error("Batch item %d failed: %s", item_id, exc)

                    inner_db.commit()
                finally:
                    inner_db.close()

        # Launch all scannable items concurrently (bounded by semaphore)
        tasks = [
            scan_one(item.id, item.target_id, item.benchmark_id)
            for item in items
            if item.benchmark_id
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any exceptions from gather
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Batch scan task %d raised: %s", i, result)

        # Update batch counters
        db.refresh(batch)
        all_items = db.query(ScanBatchItem).filter(ScanBatchItem.batch_id == batch_id).all()
        batch.completed_targets = sum(1 for it in all_items if it.status == "completed")
        batch.failed_targets = sum(1 for it in all_items if it.status == "failed")
        batch.skipped_targets = sum(1 for it in all_items if it.status == "skipped")

        if batch.failed_targets > 0 and batch.completed_targets > 0:
            batch.status = "partial"
        elif batch.failed_targets > 0 and batch.completed_targets == 0:
            batch.status = "failed"
        else:
            batch.status = "completed"

        batch.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        logger.error("Batch %d execution error: %s", batch_id, exc)
        try:
            batch = db.query(ScanBatch).filter(ScanBatch.id == batch_id).first()
            if batch:
                batch.status = "failed"
                batch.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.get("/batch/{batch_id}/status", response_model=ScanBatchStatusResponse)
def get_batch_status(batch_id: int, db: Session = Depends(get_db)):
    """Poll batch scan progress."""
    batch = db.query(ScanBatch).filter(ScanBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    items = db.query(ScanBatchItem).filter(ScanBatchItem.batch_id == batch_id).all()

    # Enrich items
    target_ids = {it.target_id for it in items}
    bm_ids = {it.benchmark_id for it in items if it.benchmark_id}
    targets_map = {t.id: t for t in db.query(Target).filter(Target.id.in_(target_ids)).all()} if target_ids else {}
    bm_map = {b.id: b for b in db.query(Benchmark).filter(Benchmark.id.in_(bm_ids)).all()} if bm_ids else {}

    resp_items = []
    for it in items:
        tgt = targets_map.get(it.target_id)
        bm = bm_map.get(it.benchmark_id) if it.benchmark_id else None
        resp_items.append(ScanBatchItemResponse(
            id=it.id,
            target_id=it.target_id,
            target_hostname=tgt.hostname if tgt else None,
            target_ip=tgt.ip_address if tgt else None,
            benchmark_id=it.benchmark_id,
            benchmark_name=(f"{bm.name} v{bm.version}" if bm and bm.version else bm.name) if bm else None,
            scan_id=it.scan_id,
            status=it.status,
            skip_reason=it.skip_reason,
            error_message=it.error_message,
        ))

    return ScanBatchStatusResponse(
        batch_id=batch.id,
        status=batch.status,
        total_targets=batch.total_targets,
        completed_targets=batch.completed_targets,
        failed_targets=batch.failed_targets,
        skipped_targets=batch.skipped_targets,
        items=resp_items,
    )


@router.post("/batch/{batch_id}/cancel")
def cancel_batch(batch_id: int, db: Session = Depends(get_db)):
    """Cancel all remaining (pending/running) items in a batch."""
    batch = db.query(ScanBatch).filter(ScanBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    if batch.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Batch is already {batch.status}")

    # Cancel pending items
    pending_items = (
        db.query(ScanBatchItem)
        .filter(
            ScanBatchItem.batch_id == batch_id,
            ScanBatchItem.status.in_(["pending", "running"]),
        )
        .all()
    )
    cancelled_count = 0
    for item in pending_items:
        # Try to cancel the underlying scan if running
        if item.scan_id:
            cancel_scan(item.scan_id)
        item.status = "skipped"
        item.skip_reason = "cancelled"
        cancelled_count += 1

    batch.status = "cancelled"
    batch.completed_at = datetime.now(timezone.utc)

    # Recompute counters
    all_items = db.query(ScanBatchItem).filter(ScanBatchItem.batch_id == batch_id).all()
    batch.completed_targets = sum(1 for it in all_items if it.status == "completed")
    batch.failed_targets = sum(1 for it in all_items if it.status == "failed")
    batch.skipped_targets = sum(1 for it in all_items if it.status == "skipped")

    db.commit()

    return {
        "batch_id": batch_id,
        "status": "cancelled",
        "cancelled_items": cancelled_count,
        "message": f"Cancelled {cancelled_count} pending items",
    }
