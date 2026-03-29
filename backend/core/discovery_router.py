"""Discovery router — transparent bridge between backend and discovery agent.

The discovery agent runs as a Docker sidecar with ``network_mode: host``
(see ``docker-compose.yml``), giving it direct Layer 2 access to the
host network — real ARP, real MACs, multicast, everything.

Routing logic:

1. **Docker + Agent reachable** → proxy to agent (``host.docker.internal:37120``)
2. **Bare metal (no Docker)** → call ``discover_network()`` directly
3. **Docker + no agent** → fallback with limited results + warning

The rest of the backend (``scans.py``) should import from HERE,
not directly from ``network_discovery``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("auditforge.discovery.router")

# ── Agent connection settings ────────────────────────────────

AGENT_HOST = os.environ.get("DISCOVERY_AGENT_HOST", "host.docker.internal")
AGENT_PORT = int(os.environ.get("DISCOVERY_AGENT_PORT", "37120"))
AGENT_BASE = f"http://{AGENT_HOST}:{AGENT_PORT}"

# Cache: None = not checked, True/False = result
_agent_available: bool | None = None
_in_docker: bool | None = None


def _is_in_docker() -> bool:
    """Detect if we're running inside a Docker container."""
    global _in_docker
    if _in_docker is not None:
        return _in_docker
    _in_docker = (
        os.path.exists("/.dockerenv")
        or os.environ.get("DOCKER_HOST_MODE") is not None
    )
    return _in_docker


async def check_agent_health() -> dict[str, Any]:
    """Probe the discovery agent and return its health status.

    Returns ``{"available": True/False, "detail": "..."}``
    """
    global _agent_available
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{AGENT_BASE}/health")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    _agent_available = True
                    logger.info("Discovery agent connected at %s", AGENT_BASE)
                    return {"available": True, "detail": "Agent connected", "url": AGENT_BASE}
    except Exception as exc:
        logger.debug("Agent health check failed: %s", exc)

    _agent_available = False
    return {"available": False, "detail": "Agent not reachable"}


async def get_discovery_engine() -> str:
    """Return which discovery engine is active.

    Returns one of: ``agent``, ``python``, ``docker_limited``.
    """
    if not _is_in_docker():
        return "python"  # bare metal — direct scan works

    if _agent_available is None:
        await check_agent_health()

    return "agent" if _agent_available else "docker_limited"


# ── In-memory progress (mirrors agent progress for the API) ──

_proxy_progress: dict[str, dict[str, Any]] = {}


def get_discovery_progress(discovery_id: str) -> dict[str, Any] | None:
    """Return progress for a discovery scan (agent-proxied or local)."""
    # Check local proxy cache first
    p = _proxy_progress.get(discovery_id)
    if p:
        return p
    # Fall back to the local network_discovery progress
    from backend.core.network_discovery import get_discovery_progress as _local_progress
    return _local_progress(discovery_id)


def cancel_discovery(discovery_id: str) -> bool:
    """Cancel a running discovery — agent or local."""
    # Try local first
    from backend.core.network_discovery import cancel_discovery as _local_cancel
    if _local_cancel(discovery_id):
        return True
    # If it's a proxied scan, tell the agent
    if discovery_id in _proxy_progress:
        asyncio.ensure_future(_agent_cancel(discovery_id))
        return True
    return False


async def _agent_cancel(discovery_id: str) -> None:
    """Send cancel request to the agent."""
    agent_scan_id = _proxy_progress.get(discovery_id, {}).get("agent_scan_id")
    if not agent_scan_id:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{AGENT_BASE}/scan/{agent_scan_id}/cancel")
    except Exception:
        pass


def cleanup_discovery(discovery_id: str) -> None:
    """Clean up completed scan data."""
    _proxy_progress.pop(discovery_id, None)
    from backend.core.network_discovery import cleanup_discovery as _local_cleanup
    _local_cleanup(discovery_id)


# ── Main discovery entry point ───────────────────────────────

async def discover_network(
    subnet: str,
    discovery_id: str | None = None,
    scan_profile: str = "standard",
) -> list[dict[str, Any]]:
    """Route discovery to the best available engine.

    - Docker + agent → proxy to host agent (real Layer 2 access)
    - Bare metal → pure-Python engine directly
    - Docker + no agent → try anyway with warning, or raise helpful error
    """
    engine = await get_discovery_engine()

    if engine == "agent":
        return await _proxy_to_agent(subnet, discovery_id)

    if engine == "docker_limited":
        # Re-check agent in case it was just started
        health = await check_agent_health()
        if health["available"]:
            return await _proxy_to_agent(subnet, discovery_id)

        logger.warning(
            "Running in Docker without discovery agent — results will be "
            "limited (no real MACs, no consumer devices). Ensure the "
            "discovery-agent service is running: docker-compose up -d"
        )

    # Direct scan (bare metal or Docker fallback)
    from backend.core.network_discovery import discover_network as _direct_discover
    return await _direct_discover(subnet, discovery_id, scan_profile)


async def _proxy_to_agent(
    subnet: str,
    discovery_id: str | None = None,
) -> list[dict[str, Any]]:
    """Proxy the full discovery lifecycle to the host agent."""
    if discovery_id is None:
        import uuid
        discovery_id = str(uuid.uuid4())[:8]

    # 1. Start scan on agent
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{AGENT_BASE}/scan",
            json={"subnet": subnet},
        )
        resp.raise_for_status()
        data = resp.json()
        agent_scan_id = data["scan_id"]

    # Initialize proxy progress
    _proxy_progress[discovery_id] = {
        "id": discovery_id,
        "agent_scan_id": agent_scan_id,
        "status": "running",
        "total": 0,
        "scanned": 0,
        "found": 0,
        "engine": "agent",
        "subnet": subnet,
        "hosts": [],
    }

    logger.info(
        "Proxying discovery %s → agent scan %s for %s",
        discovery_id, agent_scan_id, subnet,
    )

    # 2. Poll agent for progress until done
    poll_interval = 1.5  # seconds
    max_wait = 180  # 3 minute hard timeout to avoid hanging UI polls
    elapsed = 0.0
    consecutive_poll_errors = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            try:
                status_resp = await client.get(
                    f"{AGENT_BASE}/scan/{agent_scan_id}/status"
                )

                # If the agent no longer knows this scan id (e.g., restart),
                # fail fast instead of spinning until max_wait.
                if status_resp.status_code == 404:
                    _proxy_progress[discovery_id].update({
                        "status": "failed",
                        "error": "Discovery agent lost scan state (404). Please retry the scan.",
                    })
                    logger.warning(
                        "Agent scan %s returned 404 while polling; marking discovery %s failed",
                        agent_scan_id,
                        discovery_id,
                    )
                    break

                status_data = status_resp.json()
                consecutive_poll_errors = 0

                # Update proxy progress
                _proxy_progress[discovery_id].update({
                    "total": status_data.get("total", 0),
                    "scanned": status_data.get("scanned", 0),
                    "found": status_data.get("found", 0),
                    "status": status_data.get("status", "running"),
                })

                if status_data.get("status") in ("completed", "cancelled", "failed"):
                    break

            except Exception as exc:
                consecutive_poll_errors += 1
                logger.debug("Agent poll error (%d): %s", consecutive_poll_errors, exc)
                if consecutive_poll_errors >= 10:
                    _proxy_progress[discovery_id].update({
                        "status": "failed",
                        "error": "Discovery polling failed repeatedly. Please retry.",
                    })
                    logger.warning(
                        "Agent poll failed repeatedly for discovery %s; aborting",
                        discovery_id,
                    )
                    break
                continue

    # 3. Fetch results
    hosts: list[dict[str, Any]] = []
    if _proxy_progress.get(discovery_id, {}).get("status") != "failed":
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                results_resp = await client.get(
                    f"{AGENT_BASE}/scan/{agent_scan_id}/results"
                )
                if results_resp.status_code == 404:
                    _proxy_progress[discovery_id].update({
                        "status": "failed",
                        "error": "Discovery results unavailable on agent (404). Please retry.",
                    })
                    logger.warning(
                        "Agent results for scan %s returned 404; marking discovery %s failed",
                        agent_scan_id,
                        discovery_id,
                    )
                else:
                    results_data = results_resp.json()
                    hosts = results_data.get("hosts", [])
        except Exception as exc:
            logger.error("Failed to fetch agent results: %s", exc)

    # Update final progress
    final_status = _proxy_progress.get(discovery_id, {}).get("status", "completed")
    if final_status == "running" and elapsed >= max_wait:
        final_status = "failed"
        _proxy_progress[discovery_id]["error"] = "Discovery timed out. Please retry with a smaller subnet or quick profile."
    _proxy_progress[discovery_id].update({
        "status": final_status if final_status in ("failed", "cancelled") else "completed",
        "found": len(hosts),
        "hosts": hosts,
    })

    logger.info(
        "Agent scan %s complete: %d hosts discovered",
        agent_scan_id, len(hosts),
    )

    return hosts
