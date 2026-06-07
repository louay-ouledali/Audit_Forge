"""AuditForge Connect — WebSocket endpoints for agent communication."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from backend.core import agent_registry
from backend.core.agent_registry import LiveAgent
from backend.database import SessionLocal
from backend.models.connect_agent import ConnectAgent
from backend.models.connect_session import ConnectSession
from backend.models.discovery_cache import DiscoveryCache
from backend.models.scan import Scan
from backend.models.target import Target

logger = logging.getLogger("auditforge.connect.ws")

router = APIRouter(tags=["websocket"])

HEARTBEAT_INTERVAL = 30  # seconds
HEARTBEAT_TIMEOUT = 15  # seconds


# Agent WebSocket

@router.websocket("/ws/agent/{token}")
async def agent_websocket(websocket: WebSocket, token: str):
    """WebSocket endpoint for agent connections."""
    # Must accept before we can send close frames
    await websocket.accept()

    db: Session = SessionLocal()
    agent: ConnectAgent | None = None

    try:
        # Validate token
        agent = db.query(ConnectAgent).filter(ConnectAgent.token == token).first()
        if not agent:
            await websocket.close(code=4001, reason="Invalid token")
            return

        # Check session validity
        session = db.query(ConnectSession).filter(
            ConnectSession.id == agent.session_id
        ).first()
        if not session or session.status != "active":
            await websocket.close(code=4002, reason="Session expired or terminated")
            return

        # Check session expiry
        now = datetime.now(timezone.utc)
        expires = session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            session.status = "expired"
            db.commit()
            await websocket.close(code=4002, reason="Session expired")
            return

        # If a previous connection with this token exists, close the stale one
        existing = agent_registry.get_by_token(token)
        if existing:
            logger.warning("Token %s... already in registry — closing stale connection", token[:8])
            try:
                await existing.websocket.close(code=4003, reason="Replaced by new connection")
            except Exception:
                pass
            agent_registry.unregister(token)

        # Get the client IP from the WebSocket connection
        client_ip = ""
        if websocket.client:
            client_ip = websocket.client.host

        # Update agent status
        agent.status = "connected"
        agent.connected_at = now
        agent.ip_address = client_ip or agent.ip_address
        db.commit()

        # Register in live registry
        live = LiveAgent(
            agent_id=agent.id,
            session_id=agent.session_id,
            websocket=websocket,
            ip_address=client_ip,
        )
        agent_registry.register(token, live)

        # Send welcome
        await websocket.send_json({
            "type": "welcome",
            "payload": {
                "agent_id": agent.id,
                "session_id": session.id,
                "max_lifetime_seconds": session.max_agent_lifetime_seconds,
            },
        })

        logger.info("Agent %d connected (token=%s..., ip=%s)", agent.id, token[:8], client_ip)

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket, token))

        # Notify monitors
        await _broadcast_to_monitors(session.id, {
            "type": "agent_connected",
            "payload": {
                "agent_id": agent.id,
                "hostname": agent.hostname,
                "ip_address": client_ip,
                "os_type": agent.os_type,
            },
        })

        # Message loop
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "")
                payload = data.get("payload", {})

                if msg_type == "system_info":
                    await _handle_system_info(db, agent, live, payload)
                    await _broadcast_to_monitors(session.id, {
                        "type": "agent_system_info",
                        "payload": {"agent_id": agent.id, **payload},
                    })

                elif msg_type == "command_result":
                    # Forwarded to agent_executor via a pending futures dict
                    _pending_results_dispatch(token, payload)

                elif msg_type == "pong":
                    agent_registry.update_heartbeat(token)

                else:
                    logger.debug("Unknown message type from agent %d: %s", agent.id, msg_type)

        except WebSocketDisconnect:
            logger.info("Agent %d disconnected normally", agent.id)

        finally:
            heartbeat_task.cancel()

    except Exception as exc:
        logger.error("Agent WebSocket error: %s", exc)

    finally:
        # Cleanup
        agent_registry.unregister(token)
        if agent:
            try:
                agent.status = "disconnected"
                agent.disconnected_at = datetime.now(timezone.utc)
                db.commit()
            except Exception:
                pass

            # Notify monitors
            try:
                await _broadcast_to_monitors(agent.session_id, {
                    "type": "agent_disconnected",
                    "payload": {"agent_id": agent.id},
                })
            except Exception:
                pass

        db.close()


async def _handle_system_info(
    db: Session, agent: ConnectAgent, live: LiveAgent, payload: dict
) -> None:
    """Process system_info message from agent and update DB."""
    agent.hostname = payload.get("hostname", agent.hostname)
    agent.os_type = payload.get("os", agent.os_type)
    agent.os_version = payload.get("os_version", agent.os_version)
    agent.system_info = json.dumps(payload)

    # Update live registry
    live.hostname = agent.hostname or ""
    live.os_type = agent.os_type or ""

    # Auto-create or update target
    if not agent.target_id:
        session = db.query(ConnectSession).filter(
            ConnectSession.id == agent.session_id
        ).first()
        if session:
            target_type = "windows" if "windows" in (agent.os_type or "").lower() else "linux"
            target = Target(
                client_id=session.client_id,
                hostname=agent.hostname or "unknown",
                ip_address=agent.ip_address or "",
                target_type=target_type,
                connection_method="agent",
                os_details=agent.os_version,
            )
            db.add(target)
            db.flush()
            agent.target_id = target.id
            logger.info("Auto-created target %d for agent %d", target.id, agent.id)

    db.commit()

    # Persist open_ports from agent system_info into DiscoveryCache
    try:
        open_ports_raw = payload.get("open_ports", [])
        ip = agent.ip_address or (payload.get("ip_addresses", [None])[0] if payload.get("ip_addresses") else None)
        if ip and open_ports_raw:
            open_ports_data = [
                {"port": p, "service": "", "platform_hint": ""}
                for p in open_ports_raw if isinstance(p, int)
            ]
            now = datetime.now(timezone.utc)
            cached = db.query(DiscoveryCache).filter(
                DiscoveryCache.ip_address == ip
            ).order_by(DiscoveryCache.last_seen.desc()).first()
            if cached:
                cached.hostname = agent.hostname or cached.hostname
                cached.os_guess = "windows" if "windows" in (agent.os_type or "").lower() else "linux"
                cached.detection_method = "agent_connect"
                cached.last_seen = now
                cached.open_ports_json = json.dumps(open_ports_data)
            else:
                db.add(DiscoveryCache(
                    ip_address=ip,
                    hostname=agent.hostname,
                    os_guess="windows" if "windows" in (agent.os_type or "").lower() else "linux",
                    os_version=agent.os_version,
                    detection_method="agent_connect",
                    first_seen=now,
                    last_seen=now,
                    open_ports_json=json.dumps(open_ports_data),
                ))
            db.commit()
    except Exception:
        logger.debug("Failed to cache agent ports in DiscoveryCache", exc_info=True)


# Heartbeat

async def _heartbeat_loop(websocket: WebSocket, token: str) -> None:
    """Periodically ping the agent to detect stale connections."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:
                break
    except asyncio.CancelledError:
        pass


# Monitor broadcasts

_session_monitors: dict[int, list[WebSocket]] = {}


@router.websocket("/ws/session/{session_id}/monitor")
async def session_monitor(websocket: WebSocket, session_id: int):
    """Read-only WebSocket for auditor to watch live agent activity."""
    # Validate JWT from query param
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4003, reason="Authentication required")
        return
    try:
        from jose import jwt as _jwt
        from backend.config import settings
        _jwt.decode(token, settings.effective_jwt_key, algorithms=["HS256"])
    except Exception:
        # Try legacy key
        try:
            from backend.config import settings
            _jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        except Exception:
            await websocket.close(code=4003, reason="Invalid token")
            return

    await websocket.accept()

    if session_id not in _session_monitors:
        _session_monitors[session_id] = []
    _session_monitors[session_id].append(websocket)

    try:
        # Keep connection alive — just wait for disconnect
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        monitors = _session_monitors.get(session_id, [])
        if websocket in monitors:
            monitors.remove(websocket)


@router.websocket("/ws/portal/{enrollment_code}/monitor")
async def portal_monitor(websocket: WebSocket, enrollment_code: str):
    """Read-only WebSocket for target portal to watch their own session.

    Uses enrollment code (no auth needed) — same events as the auditor monitor
    plus a ``portal_init`` snapshot on connect so the portal can resume state.
    """
    await websocket.accept()

    db: Session = SessionLocal()
    session_id: int | None = None
    try:
        session = db.query(ConnectSession).filter(
            ConnectSession.enrollment_code == enrollment_code,
            ConnectSession.status == "active",
        ).first()
        if not session:
            await websocket.close(code=4001, reason="Invalid or expired enrollment code")
            return

        now = datetime.now(timezone.utc)
        expires = session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            await websocket.close(code=4002, reason="Session expired")
            return

        session_id = session.id

        # Build agent state snapshot
        agents_data = []
        target_ids = []
        for agent in session.agents:
            sys_info = None
            if agent.system_info:
                try:
                    sys_info = json.loads(agent.system_info)
                except Exception:
                    pass
            agents_data.append({
                "id": agent.id,
                "status": agent.status,
                "hostname": agent.hostname,
                "os_type": agent.os_type,
                "os_version": agent.os_version,
                "ip_address": agent.ip_address,
                "system_info": sys_info,
            })
            if agent.target_id:
                target_ids.append(agent.target_id)

        # Find most recent completed scan for any of this session's targets
        last_scan_data = None
        if target_ids:
            latest_scan = (
                db.query(Scan)
                .filter(Scan.target_id.in_(target_ids), Scan.status == "completed")
                .order_by(Scan.completed_at.desc())
                .first()
            )
            if latest_scan:
                from backend.models.benchmark import Benchmark
                bm = db.query(Benchmark).filter(Benchmark.id == latest_scan.benchmark_id).first()
                last_scan_data = {
                    "compliance_percentage": latest_scan.compliance_percentage,
                    "passed": latest_scan.passed,
                    "failed": latest_scan.failed,
                    "errors": latest_scan.errors,
                    "benchmark_name": bm.name if bm else "Unknown",
                }

        await websocket.send_json({
            "type": "portal_init",
            "payload": {
                "agents": agents_data,
                "last_scan": last_scan_data,
            },
        })

    except Exception as exc:
        logger.error("Portal monitor init error: %s", exc)
        try:
            await websocket.close(code=4000, reason="Server error")
        except Exception:
            pass
        return
    finally:
        db.close()

    # Join session monitors (same list as auditor)
    if session_id not in _session_monitors:
        _session_monitors[session_id] = []
    _session_monitors[session_id].append(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        monitors = _session_monitors.get(session_id, [])
        if websocket in monitors:
            monitors.remove(websocket)


async def _broadcast_to_monitors(session_id: int, message: dict) -> None:
    """Send a message to all auditor monitors watching this session."""
    monitors = _session_monitors.get(session_id, [])
    dead = []
    for ws in monitors:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        monitors.remove(ws)


# Command result dispatch
# Used by agent_executor to receive command results from connected agents.

_pending_futures: dict[str, dict[str, asyncio.Future]] = {}  # token -> {cmd_id -> Future}


def register_command_future(token: str, cmd_id: str) -> asyncio.Future:
    """Register a future that will be resolved when the agent sends a command_result."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    if token not in _pending_futures:
        _pending_futures[token] = {}
    _pending_futures[token][cmd_id] = future
    return future


def _pending_results_dispatch(token: str, payload: dict) -> None:
    """Dispatch a command_result to the waiting future."""
    cmd_id = payload.get("id", "")
    futures = _pending_futures.get(token, {})
    future = futures.pop(cmd_id, None)
    if future and not future.done():
        future.set_result(payload)
