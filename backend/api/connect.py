"""AuditForge Connect — REST API for session and agent management."""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.core.auth import get_current_user
from backend.config import settings
from backend.models.connect_agent import ConnectAgent
from backend.models.connect_session import ConnectSession
from backend.models.client import Client
from backend.models.target import Target
from backend.schemas.connect import (
    AgentScanRequest,
    ConnectAgentResponse,
    ConnectSessionCreate,
    ConnectSessionResponse,
    PortalValidation,
)
from backend.core import agent_registry

logger = logging.getLogger("auditforge.connect")

router = APIRouter(prefix="/connect", tags=["connect"])
_limiter = Limiter(key_func=get_remote_address)


# Helpers

def _generate_enrollment_code() -> str:
    """Generate a 12-character uppercase alphanumeric code."""
    return secrets.token_urlsafe(9)[:12].upper()


def _session_to_response(session: ConnectSession) -> dict:
    agents = session.agents or []
    return {
        "id": session.id,
        "enrollment_code": session.enrollment_code,
        "client_id": session.client_id,
        "status": session.status,
        "created_at": session.created_at,
        "expires_at": session.expires_at,
        "max_agent_lifetime_seconds": session.max_agent_lifetime_seconds,
        "notes": session.notes,
        "agent_count": len(agents),
        "agents": [_agent_to_response(a) for a in agents],
    }


def _agent_to_response(agent: ConnectAgent) -> dict:
    sys_info = None
    if agent.system_info:
        try:
            sys_info = json.loads(agent.system_info)
        except (json.JSONDecodeError, TypeError):
            sys_info = None
    return {
        "id": agent.id,
        "session_id": agent.session_id,
        "hostname": agent.hostname,
        "ip_address": agent.ip_address,
        "os_type": agent.os_type,
        "os_version": agent.os_version,
        "status": agent.status,
        "connected_at": agent.connected_at,
        "disconnected_at": agent.disconnected_at,
        "target_id": agent.target_id,
        "system_info": sys_info,
    }


def _get_valid_session(
    db: Session, session_id: int | None = None, enrollment_code: str | None = None
) -> ConnectSession | None:
    """Fetch a session and check it's still active and not expired."""
    q = db.query(ConnectSession)
    if session_id is not None:
        session = q.filter(ConnectSession.id == session_id).first()
    elif enrollment_code is not None:
        session = q.filter(ConnectSession.enrollment_code == enrollment_code).first()
    else:
        return None

    if not session:
        return None

    # Auto-expire
    now = datetime.now(timezone.utc)
    if session.status == "active" and session.expires_at:
        expires = session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            session.status = "expired"
            db.commit()
    return session


# Session CRUD

@router.post("/sessions", response_model=dict)
@_limiter.limit("2/minute")
async def create_session(request: Request, payload: ConnectSessionCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Create a new AuditForge Connect enrollment session."""
    client = db.query(Client).filter(Client.id == payload.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    code = _generate_enrollment_code()
    # Ensure uniqueness (unlikely collision but be safe)
    while db.query(ConnectSession).filter(ConnectSession.enrollment_code == code).first():
        code = _generate_enrollment_code()

    now = datetime.now(timezone.utc)
    session = ConnectSession(
        enrollment_code=code,
        client_id=payload.client_id,
        mission_id=payload.mission_id,
        status="active",
        created_at=now,
        expires_at=now + timedelta(hours=payload.expires_in_hours),
        max_agent_lifetime_seconds=payload.max_agent_lifetime_seconds,
        notes=payload.notes,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    logger.info("Connect session %d created (code=%s, client=%d)", session.id, code, payload.client_id)
    return {"data": _session_to_response(session), "message": "Session created"}


@router.get("/sessions", response_model=dict)
async def list_sessions(
    client_id: int | None = None,
    mission_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """List active connect sessions."""
    q = db.query(ConnectSession)
    if client_id:
        q = q.filter(ConnectSession.client_id == client_id)
    if mission_id:
        q = q.filter(ConnectSession.mission_id == mission_id)
    sessions = q.order_by(ConnectSession.created_at.desc()).all()
    return {"data": [_session_to_response(s) for s in sessions]}


@router.get("/sessions/{session_id}", response_model=dict)
async def get_session(session_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Get connect session details with agents."""
    session = _get_valid_session(db, session_id=session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"data": _session_to_response(session)}


@router.delete("/sessions/{session_id}")
async def terminate_session(session_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Terminate a connect session and disconnect all agents."""
    session = db.query(ConnectSession).filter(ConnectSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.status = "terminated"

    # Disconnect all live agents — use DB tokens to unregister correctly
    for agent in session.agents:
        live = agent_registry.get_by_token(agent.token)
        if live:
            try:
                await live.websocket.send_json({"type": "terminate", "payload": {"reason": "session_terminated"}})
                await live.websocket.close()
            except Exception:
                pass
            agent_registry.unregister(agent.token)

    # Update DB records
    now = datetime.now(timezone.utc)
    for agent in session.agents:
        if agent.status not in ("disconnected", "completed"):
            agent.status = "disconnected"
            agent.disconnected_at = now

    db.commit()
    logger.info("Connect session %d terminated", session_id)
    return {"message": "Session terminated"}


# Portal validation

@router.get("/portal/{enrollment_code}", response_model=dict)
async def validate_portal(enrollment_code: str, db: Session = Depends(get_db)):
    """Validate an enrollment code for the target-facing portal page."""
    session = _get_valid_session(db, enrollment_code=enrollment_code)
    if not session or session.status != "active":
        return {"data": {"valid": False}}

    client = db.query(Client).filter(Client.id == session.client_id).first()
    return {
        "data": {
            "valid": True,
            "session_id": session.id,
            "client_name": client.name if client else None,
            "expires_at": session.expires_at,
        }
    }


# Agent script generation

@router.get("/agent/{enrollment_code}/{platform}")
async def get_agent_script(
    enrollment_code: str, platform: str, request: Request, db: Session = Depends(get_db)
):
    """Generate and serve the agent script for a target device."""
    session = _get_valid_session(db, enrollment_code=enrollment_code)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Invalid or expired enrollment code")

    if platform not in ("windows", "linux"):
        raise HTTPException(status_code=400, detail="Platform must be 'windows' or 'linux'")

    # Create a ConnectAgent with a unique token
    token = secrets.token_urlsafe(32)
    agent = ConnectAgent(
        session_id=session.id,
        token=token,
        status="pending",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    # Resolve the externally-visible server host for the agent to connect to.
    # Priority: explicit ?host= param > X-Forwarded-Host > Origin/Referer > Host header
    server_host = request.query_params.get("host", "")
    if not server_host:
        server_host = request.headers.get("x-forwarded-host", "")
    if not server_host:
        origin = request.headers.get("origin", "") or request.headers.get("referer", "")
        if origin:
            # Extract host from "http://192.168.1.5:5173/..." → "192.168.1.5"
            from urllib.parse import urlparse
            parsed = urlparse(origin)
            server_host = parsed.hostname or ""
    if not server_host:
        host_header = request.headers.get("host", "")
        server_host = host_header.split(":")[0] if host_header else "localhost"

    # Render the agent script template
    import os
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)

    template_name = f"agent_{platform}.ps1.j2" if platform == "windows" else f"agent_{platform}.sh.j2"
    template = env.get_template(template_name)

    script = template.render(
        token=token,
        server_host=server_host,
        server_port=settings.SERVER_PORT,
        max_lifetime_seconds=session.max_agent_lifetime_seconds,
    )

    content_type = "text/plain; charset=utf-8"
    filename = f"auditforge_agent.{'ps1' if platform == 'windows' else 'sh'}"
    return PlainTextResponse(
        content=script,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        media_type=content_type,
    )


# Agent listing

@router.get("/sessions/{session_id}/agents", response_model=dict)
async def list_agents(session_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """List agents for a connect session, including live status."""
    session = db.query(ConnectSession).filter(ConnectSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agents_data = []
    for agent in session.agents:
        data = _agent_to_response(agent)
        # Enrich with live status from registry
        live = agent_registry.get_by_token(agent.token)
        if live and agent.status not in ("disconnected", "completed"):
            data["status"] = "connected"
        elif not live and agent.status == "connected":
            # Stale: DB says connected but agent is gone — fix it
            agent.status = "disconnected"
            data["status"] = "disconnected"
        agents_data.append(data)

    db.commit()  # persist any stale status fixes
    return {"data": agents_data}


# Scan initiation

@router.post("/sessions/{session_id}/scan", response_model=dict)
async def start_agent_scan(
    session_id: int, payload: AgentScanRequest, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    """Start scanning connected agents via their WebSocket channels."""
    session = _get_valid_session(db, session_id=session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=400, detail="Session is not active")

    from backend.models.benchmark import Benchmark
    benchmark = db.query(Benchmark).filter(Benchmark.id == payload.benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    # Get target agents
    agents_q = db.query(ConnectAgent).filter(
        ConnectAgent.session_id == session_id,
        ConnectAgent.status == "connected",
    )
    if payload.agent_ids:
        agents_q = agents_q.filter(ConnectAgent.id.in_(payload.agent_ids))
    agents = agents_q.all()

    if not agents:
        raise HTTPException(status_code=400, detail="No connected agents available")

    # Launch scans
    import asyncio
    from backend.models.scan import Scan
    from backend.models.mission_target import MissionTarget
    from backend.core.agent_executor import execute_agent_scan
    from backend.database import SessionLocal

    scan_ids = []
    skipped = 0
    for agent in agents:
        # Guard: skip agents already scanning
        if agent.status == "scanning":
            skipped += 1
            continue

        # Guard: verify agent is actually live in the registry
        live = agent_registry.get_by_token(agent.token)
        if not live:
            agent.status = "disconnected"
            skipped += 1
            continue

        # Auto-create target if not linked
        if not agent.target_id:
            target = Target(
                client_id=session.client_id,
                hostname=agent.hostname or "unknown",
                ip_address=agent.ip_address or "",
                target_type=_infer_target_type(agent.os_type),
                connection_method="agent",
                default_benchmark_id=payload.benchmark_id,
            )
            db.add(target)
            db.flush()
            agent.target_id = target.id

        # Link target to mission if session has a mission_id
        if session.mission_id and agent.target_id:
            existing_link = db.query(MissionTarget).filter(
                MissionTarget.mission_id == session.mission_id,
                MissionTarget.target_id == agent.target_id,
            ).first()
            if not existing_link:
                db.add(MissionTarget(
                    mission_id=session.mission_id,
                    target_id=agent.target_id,
                ))

        # Create scan record — linked to mission
        scan = Scan(
            target_id=agent.target_id,
            benchmark_id=payload.benchmark_id,
            mission_id=session.mission_id,
            scan_mode="network",
            status="running",
        )
        db.add(scan)
        db.flush()
        scan_ids.append(scan.id)

        agent.status = "scanning"

        # Launch as asyncio task on the current event loop (NOT run_in_executor)
        asyncio.create_task(
            execute_agent_scan(SessionLocal, scan.id, agent.token, payload.benchmark_id)
        )

    db.commit()

    if not scan_ids:
        raise HTTPException(status_code=400, detail="All selected agents are already scanning")

    logger.info("Started %d agent scans for session %d (skipped %d already scanning)", len(scan_ids), session_id, skipped)
    return {"data": {"scan_ids": scan_ids}, "message": f"{len(scan_ids)} scans started"}


def _infer_target_type(os_type: str | None) -> str:
    if not os_type:
        return "linux"
    os_lower = os_type.lower()
    if "windows" in os_lower:
        return "windows"
    if "darwin" in os_lower or "mac" in os_lower:
        return "linux"  # macOS treated as Unix-like
    return "linux"


# Portal extras

def _validate_portal_session(db: Session, enrollment_code: str) -> ConnectSession:
    """Validate enrollment code and return active session or raise 404."""
    session = db.query(ConnectSession).filter(
        ConnectSession.enrollment_code == enrollment_code,
    ).first()
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Invalid or expired enrollment code")
    now = datetime.now(timezone.utc)
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        raise HTTPException(status_code=404, detail="Session expired")
    return session


@router.get("/portal/{enrollment_code}/enable-script/{platform}")
def get_enable_script(
    enrollment_code: str,
    platform: str,
    db: Session = Depends(get_db),
):
    """Generate a WinRM (Windows) or SSH (Linux) enablement script for the target."""
    _validate_portal_session(db, enrollment_code)

    if platform not in ("windows", "linux"):
        raise HTTPException(status_code=400, detail="Platform must be 'windows' or 'linux'")

    if platform == "windows":
        script = _WINRM_ENABLE_SCRIPT
        filename = "auditforge_enable_winrm.ps1"
    else:
        script = _SSH_ENABLE_SCRIPT
        filename = "auditforge_enable_ssh.sh"

    return PlainTextResponse(
        content=script,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/portal/{enrollment_code}/usb-script/{platform}")
def get_usb_script(
    enrollment_code: str,
    platform: str,
    db: Session = Depends(get_db),
):
    """Generate a USB audit script ZIP for a target from the portal."""
    session = _validate_portal_session(db, enrollment_code)

    if platform not in ("windows", "linux"):
        raise HTTPException(status_code=400, detail="Platform must be 'windows' or 'linux'")

    # Find the most recent benchmark used for a scan in this session
    from backend.models.scan import Scan
    from backend.models.benchmark import Benchmark

    agent_target_ids = [
        a.target_id for a in session.agents if a.target_id is not None
    ]
    if not agent_target_ids:
        raise HTTPException(
            status_code=404,
            detail="No audit has been run yet. Ask your auditor to start a scan first.",
        )

    latest_scan = (
        db.query(Scan)
        .filter(Scan.target_id.in_(agent_target_ids), Scan.status == "completed")
        .order_by(Scan.completed_at.desc())
        .first()
    )
    if not latest_scan:
        raise HTTPException(
            status_code=404,
            detail="No completed scan found. Ask your auditor to run a scan first.",
        )

    benchmark = db.query(Benchmark).filter(Benchmark.id == latest_scan.benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    from backend.core.script_generator import generate_script_package
    import io

    zip_bytes, zip_filename = generate_script_package(db, benchmark_id=benchmark.id)

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


# Static enablement scripts

_WINRM_ENABLE_SCRIPT = r"""# AuditForge — Enable WinRM for Remote Auditing
# Run this script as Administrator on the target machine.

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  AuditForge — WinRM Enablement Script" -ForegroundColor Yellow
Write-Host "  =====================================" -ForegroundColor Yellow
Write-Host ""

# 1. Enable WinRM service
Write-Host "[1/5] Enabling WinRM service..." -ForegroundColor Cyan
Set-Service -Name WinRM -StartupType Automatic
Start-Service WinRM

# 2. Configure WinRM listener
Write-Host "[2/5] Configuring WinRM listener on port 5985..." -ForegroundColor Cyan
$listener = Get-ChildItem -Path WSMan:\localhost\Listener -ErrorAction SilentlyContinue |
    Where-Object { $_.Keys -contains "Transport=HTTP" }
if (-not $listener) {
    winrm create winrm/config/Listener?Address=*+Transport=HTTP | Out-Null
    Write-Host "       Created HTTP listener" -ForegroundColor Green
} else {
    Write-Host "       HTTP listener already exists" -ForegroundColor Green
}

# 3. Set WinRM configuration
Write-Host "[3/5] Setting WinRM configuration..." -ForegroundColor Cyan
Set-Item -Path WSMan:\localhost\Service\AllowUnencrypted -Value $true
Set-Item -Path WSMan:\localhost\Service\Auth\Basic -Value $true
Set-Item -Path WSMan:\localhost\Shell\MaxMemoryPerShellMB -Value 1024

# 4. Configure firewall
Write-Host "[4/5] Adding firewall rule..." -ForegroundColor Cyan
$rule = Get-NetFirewallRule -DisplayName "AuditForge WinRM" -ErrorAction SilentlyContinue
if (-not $rule) {
    New-NetFirewallRule -DisplayName "AuditForge WinRM" -Direction Inbound `
        -LocalPort 5985 -Protocol TCP -Action Allow | Out-Null
    Write-Host "       Firewall rule created" -ForegroundColor Green
} else {
    Write-Host "       Firewall rule already exists" -ForegroundColor Green
}

# 5. Set TrustedHosts
Write-Host "[5/5] Configuring TrustedHosts..." -ForegroundColor Cyan
$current = (Get-Item -Path WSMan:\localhost\Client\TrustedHosts).Value
if ($current -ne "*") {
    Set-Item -Path WSMan:\localhost\Client\TrustedHosts -Value "*" -Force
    Write-Host "       TrustedHosts set to * (restrict this in production)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  WinRM enabled successfully!" -ForegroundColor Green
Write-Host "  This machine is now accessible for remote auditing on port 5985." -ForegroundColor Gray
Write-Host ""
"""

_SSH_ENABLE_SCRIPT = r"""#!/bin/bash
# AuditForge — Enable SSH for Remote Auditing
# Run this script as root on the target machine.

set -e

echo ""
echo "  AuditForge — SSH Enablement Script"
echo "  ==================================="
echo ""

# Detect package manager
if command -v apt-get &>/dev/null; then
    PKG_MGR="apt"
elif command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
elif command -v yum &>/dev/null; then
    PKG_MGR="yum"
else
    echo "  ERROR: No supported package manager found (apt/dnf/yum)"
    exit 1
fi

# 1. Install OpenSSH server
echo "[1/4] Installing OpenSSH server..."
if ! command -v sshd &>/dev/null; then
    case $PKG_MGR in
        apt) apt-get update -qq && apt-get install -y -qq openssh-server ;;
        dnf) dnf install -y -q openssh-server ;;
        yum) yum install -y -q openssh-server ;;
    esac
    echo "       Installed openssh-server"
else
    echo "       OpenSSH server already installed"
fi

# 2. Start and enable SSH
echo "[2/4] Starting SSH service..."
systemctl enable sshd 2>/dev/null || systemctl enable ssh 2>/dev/null || true
systemctl start sshd 2>/dev/null || systemctl start ssh 2>/dev/null || true
echo "       SSH service started and enabled"

# 3. Configure firewall
echo "[3/4] Configuring firewall..."
if command -v ufw &>/dev/null; then
    ufw allow 22/tcp >/dev/null 2>&1 && echo "       ufw: port 22 allowed"
elif command -v firewall-cmd &>/dev/null; then
    firewall-cmd --permanent --add-service=ssh >/dev/null 2>&1
    firewall-cmd --reload >/dev/null 2>&1
    echo "       firewalld: SSH service allowed"
else
    echo "       No firewall detected (ufw/firewalld)"
fi

# 4. Verify
echo "[4/4] Verifying SSH..."
if ss -tlnp 2>/dev/null | grep -q ":22 " || netstat -tlnp 2>/dev/null | grep -q ":22 "; then
    echo "       SSH is listening on port 22"
else
    echo "       WARNING: SSH does not appear to be listening on port 22"
fi

echo ""
echo "  SSH enabled successfully!"
echo "  This machine is now accessible for remote auditing on port 22."
echo ""
"""
