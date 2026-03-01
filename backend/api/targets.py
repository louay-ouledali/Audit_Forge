from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.connectors import get_connector
from backend.database import get_db
from backend.models.benchmark import Benchmark
from backend.models.client import Client
from backend.models.mission import Mission
from backend.models.mission_target import MissionTarget
from backend.models.scan import Scan
from backend.models.target import Target
from backend.schemas.target import (
    TargetCreate,
    TargetDetailEnvelope,
    TargetListResponse,
    TargetResponse,
    TargetUpdate,
)
from backend.utils.encryption import decrypt_value, encrypt_value

router = APIRouter(tags=["targets"])
logger = logging.getLogger("auditforge.api.targets")


def _encrypt_fields(data: dict) -> dict:
    """Encrypt sensitive fields before storing."""
    if data.get("ssh_password"):
        data["ssh_password_encrypted"] = encrypt_value(data.pop("ssh_password"), settings.SECRET_KEY)
    else:
        data.pop("ssh_password", None)

    if data.get("db_connection_string"):
        data["db_connection_string_encrypted"] = encrypt_value(
            data.pop("db_connection_string"), settings.SECRET_KEY
        )
    else:
        data.pop("db_connection_string", None)

    if data.get("enable_password"):
        data["enable_password_encrypted"] = encrypt_value(
            data.pop("enable_password"), settings.SECRET_KEY
        )
    else:
        data.pop("enable_password", None)

    return data


def _enrich_target_response(target: Target, db: Session) -> TargetResponse:
    """Build an enriched TargetResponse with computed fields."""
    resp = TargetResponse.model_validate(target)

    # Default benchmark name
    if target.default_benchmark_id:
        bm = db.query(Benchmark).filter(Benchmark.id == target.default_benchmark_id).first()
        if bm:
            resp.default_benchmark_name = f"{bm.name} v{bm.version}" if bm.version else bm.name

    # has_enable_password flag (never expose actual password)
    resp.has_enable_password = bool(target.enable_password_encrypted)

    # Scan stats from most recent completed scan
    last_scan = (
        db.query(Scan)
        .filter(Scan.target_id == target.id, Scan.status == "completed")
        .order_by(Scan.completed_at.desc())
        .first()
    )
    if last_scan:
        resp.last_scan_compliance = last_scan.compliance_percentage
        resp.last_scan_date = last_scan.completed_at or last_scan.started_at
    resp.scan_count = db.query(Scan).filter(Scan.target_id == target.id).count()

    return resp


# ── List targets by client ───────────────────────────────────
@router.get("/clients/{client_id}/targets", response_model=TargetListResponse)
def list_targets_for_client(client_id: int, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    targets = db.query(Target).filter(Target.client_id == client_id).order_by(Target.id).all()
    result = [_enrich_target_response(t, db) for t in targets]
    return {"data": result, "total": len(result)}


# ── List targets assigned to a mission (via junction table) ──
@router.get("/missions/{mission_id}/targets", response_model=TargetListResponse)
def list_targets_for_mission(mission_id: int, db: Session = Depends(get_db)) -> dict:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    target_ids = [
        mt.target_id
        for mt in db.query(MissionTarget).filter(MissionTarget.mission_id == mission_id).all()
    ]
    targets = db.query(Target).filter(Target.id.in_(target_ids)).order_by(Target.id).all() if target_ids else []
    result = [_enrich_target_response(t, db) for t in targets]
    return {"data": result, "total": len(result)}


# ── Assign / unassign target to mission ──────────────────────
@router.post("/missions/{mission_id}/targets/{target_id}")
def assign_target_to_mission(
    mission_id: int, target_id: int, db: Session = Depends(get_db)
) -> dict:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    # Ensure target belongs to same client as mission
    if target.client_id != mission.client_id:
        raise HTTPException(status_code=400, detail="Target does not belong to same client as mission")
    existing = (
        db.query(MissionTarget)
        .filter(MissionTarget.mission_id == mission_id, MissionTarget.target_id == target_id)
        .first()
    )
    if existing:
        return {"data": None, "message": "Target already assigned to mission"}
    db.add(MissionTarget(mission_id=mission_id, target_id=target_id))
    db.commit()
    return {"data": None, "message": "Target assigned to mission"}


@router.delete("/missions/{mission_id}/targets/{target_id}")
def unassign_target_from_mission(
    mission_id: int, target_id: int, db: Session = Depends(get_db)
) -> dict:
    link = (
        db.query(MissionTarget)
        .filter(MissionTarget.mission_id == mission_id, MissionTarget.target_id == target_id)
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Target not assigned to this mission")
    db.delete(link)
    db.commit()
    return {"data": None, "message": "Target unassigned from mission"}


@router.post("/targets", response_model=TargetDetailEnvelope, status_code=201)
def create_target(payload: TargetCreate, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == payload.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    data = _encrypt_fields(payload.model_dump())
    target = Target(**data)
    db.add(target)
    db.commit()
    db.refresh(target)
    resp = _enrich_target_response(target, db)
    return {"data": resp, "message": "Target created"}


@router.get("/targets/{target_id}", response_model=TargetDetailEnvelope)
def get_target(target_id: int, db: Session = Depends(get_db)) -> dict:
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    resp = _enrich_target_response(target, db)
    return {"data": resp, "message": "success"}


@router.put("/targets/{target_id}", response_model=TargetDetailEnvelope)
def update_target(target_id: int, payload: TargetUpdate, db: Session = Depends(get_db)) -> dict:
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    data = _encrypt_fields(payload.model_dump(exclude_unset=True))
    for field, value in data.items():
        setattr(target, field, value)
    db.commit()
    db.refresh(target)
    resp = _enrich_target_response(target, db)
    return {"data": resp, "message": "Target updated"}


@router.delete("/targets/{target_id}")
def delete_target(target_id: int, db: Session = Depends(get_db)) -> dict:
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    db.delete(target)
    db.commit()
    return {"data": None, "message": "Target deleted"}


# ── Phase 2 — New Target Endpoints ──────────────────────────


# Platform-specific test commands used by test-connection
_TEST_COMMANDS: dict[str, str] = {
    "ssh": "echo ok",
    "winrm": "$env:COMPUTERNAME",
    "netmiko": " ",  # empty send; rely on connect success
    "postgresql": "SELECT 1",
    "oracle": "SELECT 1 FROM DUAL",
    "mssql": "SELECT 1",
}


def _resolve_test_command(target: Target) -> str:
    """Pick the right test command for a target's connection method."""
    method = (target.connection_method or "").lower().strip()
    if method and method in _TEST_COMMANDS:
        return _TEST_COMMANDS[method]
    ttype = (target.target_type or "").lower().strip()
    mapping = {
        "linux": "echo ok",
        "windows": "$env:COMPUTERNAME",
        "cisco_ios": " ",
        "juniper": " ",
        "fortinet": " ",
        "palo_alto": " ",
        "arista": " ",
        "hp_procurve": " ",
        "postgresql": "SELECT 1",
        "oracle": "SELECT 1 FROM DUAL",
        "mssql": "SELECT 1",
    }
    return mapping.get(ttype, "echo ok")


def _decrypt_target_password(target: Target) -> str | None:
    """Decrypt the target's SSH/WinRM password."""
    if target.ssh_password_encrypted:
        try:
            return decrypt_value(target.ssh_password_encrypted, settings.SECRET_KEY)
        except Exception:
            return None
    return None


@router.post("/targets/{target_id}/test-connection")
async def test_connection(target_id: int, db: Session = Depends(get_db)) -> dict:
    """Test connectivity to a target. Updates connection_status on the target."""
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    start = time.monotonic()
    try:
        connector = get_connector(target.target_type, target.connection_method)
    except ValueError as exc:
        target.last_connection_test = datetime.now(timezone.utc)
        target.connection_status = "failed"
        target.connection_error = f"No connector: {exc}"
        db.commit()
        return {
            "status": "failed",
            "latency_ms": 0,
            "error": str(exc),
        }

    # Attach decrypted password for connectors
    target._decrypted_password = _decrypt_target_password(target)

    try:
        await connector.connect(target)
        # Execute a lightweight test command
        test_cmd = _resolve_test_command(target)
        if test_cmd.strip():
            await connector.execute(test_cmd, timeout=10)
        await connector.disconnect()

        latency = int((time.monotonic() - start) * 1000)
        target.last_connection_test = datetime.now(timezone.utc)
        target.connection_status = "ok"
        target.connection_error = None
        db.commit()
        return {"status": "ok", "latency_ms": latency}

    except Exception as exc:
        latency = int((time.monotonic() - start) * 1000)
        error_msg = str(exc)
        target.last_connection_test = datetime.now(timezone.utc)
        target.connection_status = "failed"
        target.connection_error = error_msg
        db.commit()
        try:
            await connector.disconnect()
        except Exception:
            pass
        return {"status": "failed", "latency_ms": latency, "error": error_msg}


@router.post("/targets/{target_id}/benchmark-match")
def benchmark_match(target_id: int, db: Session = Depends(get_db)) -> dict:
    """Auto-match benchmarks based on target_type and platform_subtype."""
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    ttype = (target.target_type or "").lower().strip()
    subtype = (target.platform_subtype or "").lower().strip()

    # Map target_type → benchmark platform_family
    family_map: dict[str, str] = {
        "windows": "windows",
        "linux": "linux",
        "cisco_ios": "network",
        "juniper": "network",
        "fortinet": "network",
        "palo_alto": "network",
        "arista": "network",
        "hp_procurve": "network",
        "postgresql": "database",
        "oracle": "database",
        "mssql": "database",
    }
    family = family_map.get(ttype)
    if not family:
        return {"matches": [], "auto_set": False}

    query = db.query(Benchmark).filter(
        Benchmark.platform_family == family,
        Benchmark.status == "active",
    )
    benchmarks = query.order_by(Benchmark.name).all()

    # Score and sort by relevance
    scored: list[tuple[int, Benchmark]] = []
    for bm in benchmarks:
        score = 0
        bm_platform = (bm.platform or "").lower()
        bm_name = (bm.name or "").lower()
        # Direct type match
        if ttype in bm_platform or ttype in bm_name:
            score += 10
        # Subtype match
        if subtype and (subtype in bm_platform or subtype in bm_name):
            score += 20
        # is_ready bonus
        if bm.is_ready:
            score += 5
        scored.append((score, bm))

    scored.sort(key=lambda x: x[0], reverse=True)

    matches = [
        {
            "benchmark_id": bm.id,
            "name": bm.name,
            "version": bm.version,
            "platform": bm.platform,
            "score": score,
            "is_ready": bm.is_ready,
        }
        for score, bm in scored
    ]

    # Auto-set if exactly one high-confidence match
    auto_set = False
    if len(scored) == 1 or (len(scored) > 1 and scored[0][0] >= 20 and scored[0][0] > scored[1][0]):
        best = scored[0][1]
        target.default_benchmark_id = best.id
        db.commit()
        auto_set = True

    return {"matches": matches, "auto_set": auto_set}


@router.get("/targets/{target_id}/scan-readiness")
def scan_readiness(target_id: int, db: Session = Depends(get_db)) -> dict:
    """Return a readiness checklist for scanning this target."""
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    checks: list[dict] = []
    blockers: list[str] = []
    suggestions: list[str] = []

    # 1. Credentials check
    has_creds = bool(
        target.ssh_password_encrypted
        or target.ssh_key_path
        or target.db_connection_string_encrypted
    )
    if has_creds:
        detail = f"Username: {target.ssh_username}" if target.ssh_username else "Credentials configured"
        checks.append({"name": "credentials", "status": "ok", "detail": detail})
    else:
        checks.append({"name": "credentials", "status": "failed", "detail": "No credentials configured"})
        blockers.append("No credentials configured for this target")
        suggestions.append("Configure SSH/WinRM/DB credentials in the target settings")

    # 2. Benchmark check
    if target.default_benchmark_id:
        bm = db.query(Benchmark).filter(Benchmark.id == target.default_benchmark_id).first()
        if bm:
            label = f"{bm.name} v{bm.version}" if bm.version else bm.name
            checks.append({"name": "benchmark", "status": "ok", "detail": label})
        else:
            checks.append({"name": "benchmark", "status": "failed", "detail": "Assigned benchmark not found"})
            blockers.append("Assigned benchmark no longer exists")
    else:
        checks.append({"name": "benchmark", "status": "failed", "detail": "No benchmark assigned"})
        blockers.append("No benchmark assigned — use auto-match or set one manually")
        suggestions.append("Click 'Auto-Match Benchmark' or select one from the dropdown")

    # 3. Connection test status
    conn_status = target.connection_status or "untested"
    if conn_status == "ok":
        checks.append({"name": "connection", "status": "ok", "detail": "Last test passed"})
    elif conn_status == "failed":
        err = target.connection_error or "Unknown error"
        checks.append({"name": "connection", "status": "failed", "detail": err})
        blockers.append(f"Connection test failed: {err}")
        # Platform-specific suggestion
        ttype = (target.target_type or "").lower()
        if ttype == "windows":
            suggestions.append("Ensure WinRM is enabled — click 'Setup Help' on the target card to download the setup script, or use the USB workflow")
        elif ttype == "linux":
            suggestions.append("Verify SSH access — click 'Setup Help' for the enable_ssh script and instructions")
        elif ttype in ("cisco_ios", "juniper", "fortinet", "palo_alto", "arista", "hp_procurve"):
            suggestions.append("Check SSH is enabled on the device — click 'Setup Help' for vendor-specific commands")
        else:
            suggestions.append("Test connectivity and check firewall rules — click 'Setup Help' for preparation scripts")
    else:
        checks.append({"name": "connection", "status": "warning", "detail": "Not tested yet"})
        suggestions.append("Run 'Test Connection' to verify connectivity before scanning")

    # 4. Connector availability check
    try:
        get_connector(target.target_type, target.connection_method)
        checks.append({"name": "connector", "status": "ok", "detail": f"Connector available for {target.target_type}"})
    except ValueError:
        checks.append({"name": "connector", "status": "failed", "detail": f"No connector for {target.target_type}"})
        blockers.append(f"No connector available for target type '{target.target_type}'")

    ready = len(blockers) == 0
    return {
        "ready": ready,
        "checks": checks,
        "blockers": blockers,
        "suggestions": suggestions,
    }


@router.get("/targets/{target_id}/last-scan")
def last_scan(target_id: int, db: Session = Depends(get_db)) -> dict:
    """Return the most recent scan summary for this target."""
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    scan = (
        db.query(Scan)
        .filter(Scan.target_id == target_id)
        .order_by(Scan.created_at.desc())
        .first()
    )
    if not scan:
        return {"data": None, "message": "No scans found for this target"}

    bm = db.query(Benchmark).filter(Benchmark.id == scan.benchmark_id).first() if scan.benchmark_id else None
    return {
        "data": {
            "scan_id": scan.id,
            "status": scan.status,
            "scan_mode": scan.scan_mode,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
            "compliance_percentage": scan.compliance_percentage,
            "passed": scan.passed or 0,
            "failed": scan.failed or 0,
            "errors": scan.errors or 0,
            "total_rules_checked": scan.total_rules_checked or 0,
            "benchmark_name": bm.name if bm else None,
            "benchmark_version": bm.version if bm else None,
        },
        "message": "success",
    }


from pathlib import Path

from backend.core.prerequisites import get_prerequisite_guide
from fastapi.responses import FileResponse


# Platform-specific prerequisite guides — now in backend/core/prerequisites.py

# Directory containing downloadable preparation scripts
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

# Allowed script filenames (prevent directory traversal)
_ALLOWED_SCRIPTS = {
    "Enable_WinRM.ps1",
    "Enable_OpenSSH_Windows.ps1",
    "enable_ssh_linux.sh",
    "network_device_ssh_setup.txt",
}


@router.get("/targets/{target_id}/prerequisites")
def prerequisites(target_id: int, db: Session = Depends(get_db)) -> dict:
    """Return platform-specific setup instructions for a target."""
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    ttype = (target.target_type or "").lower().strip()
    return get_prerequisite_guide(ttype, target.connection_method)


@router.get("/scripts/{filename}")
def download_script(filename: str):
    """Download a preparation script by filename."""
    if filename not in _ALLOWED_SCRIPTS:
        raise HTTPException(status_code=404, detail="Script not found")

    filepath = _SCRIPTS_DIR / filename
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail="Script file missing")

    # Determine MIME type
    suffix = filepath.suffix.lower()
    media_types = {
        ".ps1": "application/octet-stream",
        ".sh": "application/x-shellscript",
        ".txt": "text/plain",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type=media_type,
    )

