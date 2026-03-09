from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.missions import check_mission_lock
from backend.core.discovery_router import (
    cancel_discovery,
    check_agent_health,
    cleanup_discovery,  # UNUSED — safe to remove
    discover_network,
    get_discovery_engine,
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
from backend.models.discovery_cache import DiscoveryCache
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
    scan_profile: str = "standard"  # quick | standard | thorough


class DiscoveryResponse(BaseModel):
    discovery_id: str
    status: str
    engine: str = ""  # nmap | python


@router.post("/discover", response_model=DiscoveryResponse)
async def start_discovery(payload: DiscoveryRequest):
    """Start a network discovery scan on the given subnet."""
    discovery_id = str(uuid.uuid4())[:8]
    engine = await get_discovery_engine()

    async def _run_discovery():
        try:
            await discover_network(
                payload.subnet,
                discovery_id=discovery_id,
                scan_profile=payload.scan_profile,
            )
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
    return DiscoveryResponse(discovery_id=discovery_id, status="running", engine=engine)


@router.get("/discover/profiles")
async def get_scan_profiles():
    """Return available scan profiles and the active engine."""
    engine = await get_discovery_engine()
    # Profiles are meaningful for all engines
    profiles = {
        "quick": {"label": "Quick (ping sweep)", "description": "Host discovery only. ~15 seconds."},
        "standard": {"label": "Standard (OS + services)", "description": "Recommended. Full fingerprinting."},
        "thorough": {"label": "Thorough (deep scan)", "description": "Slowest but most data."},
    }
    return {"engine": engine, "profiles": profiles}


@router.get("/discover/{discovery_id}/status")
async def get_discovery_status(discovery_id: str):
    """Return current progress/results for a discovery scan."""
    progress = get_discovery_progress(discovery_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Discovery not found")
    return progress


@router.post("/discover/{discovery_id}/cancel")
async def cancel_discovery_scan(discovery_id: str):
    """Request cancellation of a running discovery scan."""
    if cancel_discovery(discovery_id):
        return {"status": "cancel_requested", "discovery_id": discovery_id}
    raise HTTPException(status_code=404, detail="Discovery not found or not running")


@router.get("/discover/{discovery_id}/results")
async def get_discovery_results(
    discovery_id: str,
    mission_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Return enriched results from a completed async discovery scan.

    This does NOT re-scan — it reads the hosts from the in-memory progress
    dict, upserts them into the discovery cache, and enriches them with
    existing target / benchmark data.
    """
    progress = get_discovery_progress(discovery_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Discovery not found")
    if progress.get("status") not in ("completed", "cancelled"):
        return {"status": progress.get("status"), "hosts": []}

    raw_hosts = progress.get("hosts", [])
    subnet = progress.get("subnet", "")

    # Upsert into discovery cache + enrich with target/benchmark info
    if raw_hosts:
        _upsert_discovery_cache(raw_hosts, subnet, db)
        enriched = _enrich_discovered_hosts(raw_hosts, mission_id, db)
    else:
        enriched = raw_hosts

    return {
        "status": progress.get("status"),
        "hosts": enriched,
        "engine": progress.get("engine", "python"),
        "total_scanned": len(enriched),
    }


@router.get("/discover/agent-status")
async def get_agent_status():
    """Check whether the host discovery agent is reachable."""
    health = await check_agent_health()
    engine = await get_discovery_engine()
    return {"engine": engine, **health}


@router.delete("/discover/cache")
async def clear_discovery_cache(db: Session = Depends(get_db)):
    """Clear all entries from the discovery cache table."""
    count = db.query(DiscoveryCache).count()
    db.query(DiscoveryCache).delete()
    db.commit()
    return {"cleared": count}


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
        hosts = await discover_network(
            payload.subnet,
            scan_profile=payload.scan_profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Upsert results into discovery cache (writes first_seen / last_seen)
    _upsert_discovery_cache(hosts, payload.subnet, db)

    # Enrich with existing target info and benchmark suggestions
    enriched = _enrich_discovered_hosts(hosts, payload.mission_id, db)
    engine = await get_discovery_engine()
    return {"hosts": enriched, "total_scanned": len(enriched), "engine": engine}


# ── Discovery cache upsert ───────────────────────────────────


def _upsert_discovery_cache(
    hosts: list[dict],
    subnet: str,
    db: Session,
) -> None:
    """Upsert discovered hosts into the discovery_cache table.

    Matching priority: MAC address first, then IP address.
    Sets first_seen on insert, updates last_seen on every scan.
    """
    now = datetime.now(timezone.utc)

    # Build lookup of existing cache entries for this subnet area
    # (use all entries — a host may move between subnets)
    existing_by_mac: dict[str, DiscoveryCache] = {}
    existing_by_ip: dict[str, DiscoveryCache] = {}
    cache_entries = db.query(DiscoveryCache).all()
    for entry in cache_entries:
        if entry.mac_address:
            existing_by_mac[entry.mac_address.upper()] = entry
        if entry.ip_address:
            existing_by_ip[entry.ip_address] = entry

    for host in hosts:
        ip = host.get("ip", "")
        mac = (host.get("mac_address") or "").upper()

        # Find existing cache entry (MAC-first)
        cached: DiscoveryCache | None = None
        if mac:
            cached = existing_by_mac.get(mac)
        if not cached and ip:
            cached = existing_by_ip.get(ip)

        if cached:
            # Update existing entry
            cached.ip_address = ip or cached.ip_address
            if mac:
                cached.mac_address = mac
            cached.hostname = host.get("hostname") or cached.hostname
            cached.os_guess = host.get("os_guess") or cached.os_guess
            cached.os_version = host.get("os_version") or cached.os_version
            cached.vendor = host.get("vendor") or cached.vendor
            cached.device_model = host.get("device_model") or cached.device_model
            cached.firmware = host.get("firmware") or cached.firmware
            cached.domain = host.get("domain") or cached.domain
            cached.detection_method = host.get("detection_method") or cached.detection_method
            cached.confidence = max(host.get("confidence", 0), cached.confidence or 0)
            cached.subnet = subnet
            cached.last_seen = now
            if host.get("open_ports"):
                cached.open_ports_json = json.dumps(host["open_ports"])
            if host.get("connection_methods"):
                cached.connection_methods_json = json.dumps(host["connection_methods"])
            # Inject first_seen/last_seen back into the host dict for the response
            host["first_seen"] = cached.first_seen.isoformat() if cached.first_seen else now.isoformat()
            host["last_seen"] = now.isoformat()
            host["is_new"] = False
        else:
            # Insert new entry
            new_entry = DiscoveryCache(
                ip_address=ip,
                mac_address=mac or None,
                subnet=subnet,
                hostname=host.get("hostname"),
                os_guess=host.get("os_guess"),
                os_version=host.get("os_version"),
                vendor=host.get("vendor"),
                device_model=host.get("device_model"),
                firmware=host.get("firmware"),
                domain=host.get("domain"),
                detection_method=host.get("detection_method"),
                confidence=host.get("confidence", 0),
                open_ports_json=json.dumps(host.get("open_ports", [])),
                connection_methods_json=json.dumps(host.get("connection_methods", [])),
                first_seen=now,
                last_seen=now,
            )
            db.add(new_entry)
            host["first_seen"] = now.isoformat()
            host["last_seen"] = now.isoformat()
            host["is_new"] = True

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Failed to upsert discovery cache", exc_info=True)


# ── Discovery enrichment helper ──────────────────────────────


def _enrich_discovered_hosts(
    hosts: list[dict],
    mission_id: int | None,
    db: Session,
) -> list[dict]:
    """Add already_added, existing_target_id, and suggested_benchmark to discovered hosts.

    Matching priority:
    1. MAC address (persistent hardware identity — survives IP changes)
    2. IP address (fallback for targets without MAC)

    When a MAC-matched target has a stale IP, its ip_address is auto-updated
    so the auditor always works with the current address.
    """
    # Build lookups of existing targets keyed by MAC and IP
    all_targets = db.query(Target).all()
    mac_to_target: dict[str, Target] = {}
    ip_to_target: dict[str, Target] = {}
    for t in all_targets:
        if t.mac_address:
            mac_to_target[t.mac_address.upper()] = t
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
    ip_updated_targets: list[int] = []

    for host in hosts:
        ip = host.get("ip", "")
        mac = (host.get("mac_address", "") or "").upper()
        os_guess = (host.get("os_guess", "") or "").lower()

        # Match: prefer MAC (persistent) → fallback to IP
        existing: Target | None = None
        match_method = ""
        if mac:
            existing = mac_to_target.get(mac)
            if existing:
                match_method = "mac"
        if not existing and ip:
            existing = ip_to_target.get(ip)
            if existing:
                match_method = "ip"

        host["already_added"] = existing is not None
        host["existing_target_id"] = existing.id if existing else None
        host["already_assigned"] = existing.id in assigned_ids if existing else False
        host["match_method"] = match_method

        # Auto re-tie: if MAC-matched target has a different IP, update it
        if existing and match_method == "mac" and ip and existing.ip_address != ip:
            old_ip = existing.ip_address
            existing.ip_address = ip
            ip_updated_targets.append(existing.id)
            logger.info(
                "Auto re-tied target %d (%s): IP %s → %s (MAC %s)",
                existing.id, existing.hostname or "", old_ip or "?", ip, mac,
            )

        # Also store/update MAC on existing target if it was missing
        if existing and mac and not existing.mac_address:
            existing.mac_address = mac

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

    # Commit any IP re-ties or MAC backfills
    if ip_updated_targets:
        db.commit()

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

    check_mission_lock(payload.mission_id, db)

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
    benchmark_id: int | None = None,
    scan_mode: str | None = None,
    started_after: str | None = None,
    started_before: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List all scans with optional filters and pagination."""
    from backend.models.target import Target as TargetModel
    from backend.models.mission import Mission as MissionModel
    from backend.models.client import Client as ClientModel

    query = db.query(Scan)
    if target_id:
        query = query.filter(Scan.target_id == target_id)
    if mission_id:
        query = query.filter(Scan.mission_id == mission_id)
    if status:
        query = query.filter(Scan.status == status)
    if benchmark_id:
        query = query.filter(Scan.benchmark_id == benchmark_id)
    if scan_mode:
        query = query.filter(Scan.scan_mode == scan_mode)
    if started_after:
        from datetime import datetime as _dt
        try:
            query = query.filter(Scan.started_at >= _dt.fromisoformat(started_after))
        except ValueError:
            pass
    if started_before:
        from datetime import datetime as _dt
        try:
            query = query.filter(Scan.started_at <= _dt.fromisoformat(started_before))
        except ValueError:
            pass

    total = query.count()
    scans = query.order_by(Scan.created_at.desc()).offset(skip).limit(limit).all()

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

    return {"data": result, "total": total}


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

    check_mission_lock(mission_id, db)

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


# ── Smart Import — Preview ───────────────────────────────────


@router.post("/smart-import/preview")
async def smart_import_preview(
    file: UploadFile = File(...),
    client_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    """Preview what a Smart Import would produce WITHOUT creating anything.

    Returns auto-detected platform, benchmark, finding counts, etc.
    Used by the frontend ImportPreviewModal.
    """
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File too large")

    content = raw.decode("utf-8", errors="replace").lstrip("\ufeff\ufffe")
    filename = file.filename or ""

    from backend.importers.import_orchestrator import ImportOrchestrator
    orchestrator = ImportOrchestrator(db)

    try:
        preview_data = orchestrator.preview(content, filename, client_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return preview_data


# ── Smart Import — Execute ───────────────────────────────────


@router.post("/smart-import")
async def smart_import(
    mission_id: int | None = Form(None),
    client_id: int | None = Form(None),
    target_id: int | None = Form(None),
    run_fp_detection: bool = Form(True),
    allow_benchmark_creation: bool = Form(True),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Auto-detect target and benchmark from uploaded results, creating if needed.

    Accepts:
    - ZIP (with system_info.json + audit_results.json) — legacy AuditForge format
    - Standalone audit_results.json — legacy AuditForge format
    - Nessus CSV (.csv) — compliance scan export
    - Nessus HTML (.html/.htm) — compliance scan report (Phase 2)

    For Nessus files: uses the ImportOrchestrator pipeline (reverse engineering).
    For legacy files: uses the existing direct import flow.
    """
    import io
    import json
    import zipfile

    check_mission_lock(mission_id, db)

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File too large")

    filename = file.filename or ""

    # ── Nessus file detection → delegate to ImportOrchestrator ──
    content_str = raw.decode("utf-8", errors="replace").lstrip("\ufeff\ufffe")
    is_nessus = (
        filename.lower().endswith((".csv", ".html", ".htm", ".nessus", ".xml"))
        or _looks_like_nessus(content_str)
    )

    if is_nessus:
        from backend.importers.import_orchestrator import ImportOrchestrator
        orchestrator = ImportOrchestrator(db)

        try:
            result = orchestrator.execute(
                content_str,
                filename,
                client_id=client_id,
                mission_id=mission_id,
                target_id=target_id,
                run_fp_detection=run_fp_detection,
                allow_benchmark_creation=allow_benchmark_creation,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            import traceback
            logger.error("Smart Import execute failed: %s\n%s", exc, traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail="Import failed due to an internal error. Check server logs for details.",
            )

        return result.to_dict()

    # ── Legacy AuditForge format (ZIP / JSON) ────────────────
    system_info: dict | None = None
    result_content: str | None = None

    # ── Extract from ZIP ─────────────────────────────────────
    if filename.endswith(".zip") or raw[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()

                # Try to find system_info.json
                si_name = next((n for n in names if n.endswith("system_info.json")), None)
                if si_name:
                    si_data = zf.read(si_name).decode("utf-8", errors="replace")
                    try:
                        system_info = json.loads(si_data)
                    except json.JSONDecodeError:
                        pass

                # Find audit_results
                ar_name = next((n for n in names if n.endswith("audit_results.json")), None)
                if not ar_name:
                    ar_name = next((n for n in names if n.endswith(".json") and "system_info" not in n and "rules_reference" not in n), None)
                if not ar_name:
                    ar_name = next((n for n in names if n.endswith(".txt")), None)
                if not ar_name and names:
                    ar_name = names[0]
                if not ar_name:
                    raise HTTPException(status_code=400, detail="ZIP file is empty")

                data = zf.read(ar_name)
                if len(data) > MAX_DECOMPRESSED_SIZE:
                    raise HTTPException(status_code=400, detail="Decompressed file too large")
                result_content = data.decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP file")
    else:
        result_content = raw.decode("utf-8", errors="replace")
        # Try to parse as JSON and look for embedded system info
        try:
            parsed = json.loads(result_content.strip().lstrip("\ufeff"))
            if isinstance(parsed, dict) and "system_info" in parsed:
                system_info = parsed["system_info"]
        except (json.JSONDecodeError, TypeError):
            pass

    if not result_content:
        raise HTTPException(status_code=400, detail="No result content found in upload")

    # ── Resolve benchmark ────────────────────────────────────
    benchmark: Benchmark | None = None
    if system_info:
        bm_name = system_info.get("benchmark", "")
        bm_version = (system_info.get("benchmark_version") or "").lstrip("v")
        if bm_name:
            q = db.query(Benchmark).filter(Benchmark.name.ilike(f"%{bm_name}%"))
            if bm_version:
                q = q.filter(Benchmark.version == bm_version)
            benchmark = q.first()
            if not benchmark and bm_version:
                benchmark = db.query(Benchmark).filter(Benchmark.name.ilike(f"%{bm_name}%")).first()

    if not benchmark:
        # Fallback: pick the first benchmark (common single-benchmark setups)
        benchmark = db.query(Benchmark).first()

    if not benchmark:
        raise HTTPException(status_code=400, detail="No benchmark found. Please upload a benchmark first.")

    # ── Resolve or create target ─────────────────────────────
    target: Target | None = None
    target_was_created = False

    # Derive client_id from mission if not provided
    if not client_id and mission_id:
        from backend.models.mission import Mission
        m = db.query(Mission).filter(Mission.id == mission_id).first()
        if m:
            client_id = m.client_id

    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="client_id or mission_id is required so the target can be assigned to a client.",
        )

    if system_info:
        hostname = system_info.get("hostname", "")
        ips = [ip.strip() for ip in (system_info.get("ip_addresses") or "").split(",") if ip.strip()]
        os_info = system_info.get("os", "")

        # Try matching by hostname within the client
        if hostname:
            target = (
                db.query(Target)
                .filter(Target.client_id == client_id, Target.hostname.ilike(hostname))
                .first()
            )

        # Try matching by IP
        if not target and ips:
            for ip in ips:
                target = (
                    db.query(Target)
                    .filter(Target.client_id == client_id, Target.ip_address == ip)
                    .first()
                )
                if target:
                    break

        # Create new target
        if not target:
            target_type = "windows"
            os_lower = os_info.lower()
            if "linux" in os_lower or "ubuntu" in os_lower or "centos" in os_lower or "debian" in os_lower:
                target_type = "linux"
            elif "cisco" in os_lower or "juniper" in os_lower or "fortinet" in os_lower:
                target_type = "network"

            target = Target(
                client_id=client_id,
                hostname=hostname or "imported-target",
                ip_address=ips[0] if ips else None,
                target_type=target_type,
                os_details=os_info or None,
                default_benchmark_id=benchmark.id,
            )
            db.add(target)
            db.commit()
            db.refresh(target)
            target_was_created = True

    if not target:
        raise HTTPException(
            status_code=400,
            detail="Could not detect target info from results. Upload a ZIP with system_info.json or use the standard import.",
        )

    # Ensure target is assigned to the mission
    if mission_id:
        existing = (
            db.query(MissionTarget)
            .filter(MissionTarget.mission_id == mission_id, MissionTarget.target_id == target.id)
            .first()
        )
        if not existing:
            db.add(MissionTarget(mission_id=mission_id, target_id=target.id))
            db.commit()

    # ── Create scan & import ─────────────────────────────────
    scan = Scan(
        target_id=target.id,
        benchmark_id=benchmark.id,
        mission_id=mission_id,
        scan_mode="import",
        status="pending",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    try:
        from backend.core.result_importer import detect_format_and_import, finalize_scan_stats
        stats = detect_format_and_import(result_content, scan.id, benchmark.id, db)
        finalize_scan_stats(scan, stats, db)
    except ValueError as exc:
        db.delete(scan)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        **stats,
        "scan_id": scan.id,
        "target_id": target.id,
        "target_hostname": target.hostname,
        "target_ip": target.ip_address,
        "benchmark_id": benchmark.id,
        "benchmark_name": benchmark.name,
        "target_created": target_was_created,
    }


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

    # Reject deletion of running scans
    if scan.status in ("running", "in_progress", "pending"):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a scan that is currently running. Cancel it first.",
        )

    check_mission_lock(scan.mission_id, db)

    db.delete(scan)
    db.commit()
    return {"message": "Scan deleted", "scan_id": scan_id}


# ── Findings for a scan ──────────────────────────────────────


@router.get("/{scan_id}/findings")
def list_scan_findings(
    scan_id: int,
    status: str | None = None,
    severity: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """List findings for a specific scan with optional filters and pagination."""
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

    total = query.count()
    findings = query.order_by(Finding.id).offset(skip).limit(limit).all()

    # Batch-fetch rules in one query instead of N+1
    rule_ids = {f.rule_id for f in findings if f.rule_id}
    rules_map: dict[int, Rule] = {}
    if rule_ids:
        for r in db.query(Rule).filter(Rule.id.in_(rule_ids)).all():
            rules_map[r.id] = r

    result = []
    for f in findings:
        rule = rules_map.get(f.rule_id) if f.rule_id else None
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
    return {"data": result, "total": total}


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

    check_mission_lock(scan.mission_id, db)

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

    check_mission_lock(payload.mission_id, db)

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


# ── Private helpers ──────────────────────────────────────────


def _looks_like_nessus(content: str) -> bool:
    """Quick heuristic to detect Nessus CSV, HTML, or XML content."""
    from backend.importers.csv_parser import detect_nessus_csv
    from backend.importers.html_parser import detect_nessus_html
    from backend.importers.nessus_xml_parser import detect_nessus_xml
    from backend.importers.qualys_parser import detect_qualys_csv, detect_qualys_xml
    from backend.importers.openvas_parser import detect_openvas_xml

    if detect_nessus_csv(content):
        return True
    if detect_nessus_html(content):
        return True
    if detect_nessus_xml(content):
        return True
    if detect_qualys_csv(content):
        return True
    if detect_qualys_xml(content):
        return True
    if detect_openvas_xml(content):
        return True
    return False


# ── Phase 3: Scan Comparison ────────────────────────────────


@router.get("/compare/{scan_a_id}/{scan_b_id}")
def compare_scans(
    scan_a_id: int,
    scan_b_id: int,
    db: Session = Depends(get_db),
):
    """Compare two scans — shows rule-by-rule status differences.

    Works for same benchmark or overlapping benchmarks (matches by section_number).
    """
    from backend.models.finding import Finding
    from backend.models.rule import Rule
    from backend.schemas.benchmark import ScanComparisonItem, ScanComparisonResponse

    scan_a = db.query(Scan).filter(Scan.id == scan_a_id).first()
    scan_b = db.query(Scan).filter(Scan.id == scan_b_id).first()
    if not scan_a or not scan_b:
        raise HTTPException(status_code=404, detail="One or both scans not found")

    bm_a = db.query(Benchmark).filter(Benchmark.id == scan_a.benchmark_id).first()
    bm_b = db.query(Benchmark).filter(Benchmark.id == scan_b.benchmark_id).first()

    # Build section→status maps for each scan
    def _build_map(scan_id: int) -> dict[str, tuple[str, str, str]]:
        """Returns {section_number: (status, severity, title)}"""
        results = (
            db.query(Finding.status, Rule.section_number, Rule.severity, Rule.title)
            .join(Rule, Rule.id == Finding.rule_id)
            .filter(Finding.scan_id == scan_id)
            .all()
        )
        return {
            r.section_number: (r.status, r.severity or "medium", r.title or "")
            for r in results
        }

    map_a = _build_map(scan_a_id)
    map_b = _build_map(scan_b_id)

    all_sections = sorted(set(map_a.keys()) | set(map_b.keys()))

    items: list[ScanComparisonItem] = []
    improved = regressed = unchanged = new = removed = 0

    _PASS_STATUSES = {"PASS", "pass", "Pass"}
    _FAIL_STATUSES = {"FAIL", "fail", "Fail", "ERROR", "error"}

    for sec in all_sections:
        a_info = map_a.get(sec)
        b_info = map_b.get(sec)

        a_status = a_info[0] if a_info else None
        b_status = b_info[0] if b_info else None
        severity = (b_info or a_info or ("", "medium", ""))[1]
        title = (b_info or a_info or ("", "", ""))[2]

        changed = a_status != b_status

        if a_status is None and b_status is not None:
            new += 1
        elif a_status is not None and b_status is None:
            removed += 1
        elif changed:
            if a_status in _FAIL_STATUSES and b_status in _PASS_STATUSES:
                improved += 1
            elif a_status in _PASS_STATUSES and b_status in _FAIL_STATUSES:
                regressed += 1
            else:
                # Other transitions (e.g. N/A → PASS)
                if b_status in _PASS_STATUSES:
                    improved += 1
                elif b_status in _FAIL_STATUSES:
                    regressed += 1
        else:
            unchanged += 1

        items.append(ScanComparisonItem(
            section_number=sec,
            title=title,
            scan_a_status=a_status,
            scan_b_status=b_status,
            changed=changed,
            severity=severity,
        ))

    return ScanComparisonResponse(
        scan_a_id=scan_a_id,
        scan_b_id=scan_b_id,
        scan_a_benchmark=f"{bm_a.name} v{bm_a.version}" if bm_a else None,
        scan_b_benchmark=f"{bm_b.name} v{bm_b.version}" if bm_b else None,
        scan_a_date=scan_a.completed_at.isoformat() if scan_a.completed_at else (scan_a.created_at.isoformat() if scan_a.created_at else None),
        scan_b_date=scan_b.completed_at.isoformat() if scan_b.completed_at else (scan_b.created_at.isoformat() if scan_b.created_at else None),
        total_rules_compared=len(items),
        rules_improved=improved,
        rules_regressed=regressed,
        rules_unchanged=unchanged,
        rules_new=new,
        rules_removed=removed,
        items=items,
    )
