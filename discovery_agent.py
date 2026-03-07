#!/usr/bin/env python3
"""AuditForge Discovery Agent — network scanner with real Layer 2 access.

Runs as a Docker sidecar service with ``network_mode: host``, giving it
direct access to the host's physical NIC.  On Linux production servers
this means full ARP, real MACs, multicast, and all UDP probes work.

Capabilities:
  - Real MAC addresses from ARP table (not Docker gateway MACs)
  - ICMP ping that finds phones, TVs, IoT (no ghost responses)
  - Multicast: mDNS (5353) + SSDP (1900) for consumer devices
  - UDP probes: NetBIOS, SNMP, DNS, NTP
  - All 47+ TCP ports with proper service labels

Deployment:
    Automatically started by ``docker-compose up``.
    See the ``discovery-agent`` service in docker-compose.yml.

The AuditForge backend reaches this agent via host.docker.internal:37120.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from http import HTTPStatus
from typing import Any

# ── Ensure the project root is on sys.path so imports work ───
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("discovery_agent")

# In-memory store for async scan results
_scans: dict[str, dict[str, Any]] = {}


async def _run_scan(scan_id: str, subnet: str) -> None:
    """Execute the pure-Python discovery engine and store results."""
    from backend.core.network_discovery import discover_network

    _scans[scan_id] = {
        "id": scan_id,
        "status": "running",
        "subnet": subnet,
        "total": 0,
        "scanned": 0,
        "found": 0,
        "hosts": [],
        "engine": "agent",
    }

    try:
        hosts = await discover_network(subnet, discovery_id=scan_id)
        _scans[scan_id]["status"] = "completed"
        _scans[scan_id]["hosts"] = hosts
        _scans[scan_id]["found"] = len(hosts)
        logger.info("Scan %s completed: %d hosts found", scan_id, len(hosts))
    except Exception as exc:
        logger.error("Scan %s failed: %s", scan_id, exc)
        _scans[scan_id]["status"] = "failed"
        _scans[scan_id]["error"] = str(exc)


# ── HTTP server using aiohttp (lightweight, async) ───────────

async def run_server(host: str, port: int) -> None:
    try:
        from aiohttp import web
    except ImportError:
        logger.error(
            "aiohttp is required. Install with:  pip install aiohttp"
        )
        sys.exit(1)

    routes = web.RouteTableDef()

    @routes.get("/health")
    async def health(request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "agent": "auditforge-discovery",
            "version": "1.0",
        })

    @routes.post("/scan")
    async def start_scan(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Invalid JSON"}, status=HTTPStatus.BAD_REQUEST
            )

        subnet = body.get("subnet", "").strip()
        if not subnet:
            return web.json_response(
                {"error": "Missing 'subnet' field"}, status=HTTPStatus.BAD_REQUEST
            )

        scan_id = str(uuid.uuid4())[:8]
        # Launch scan in background
        asyncio.ensure_future(_run_scan(scan_id, subnet))

        return web.json_response({
            "scan_id": scan_id,
            "status": "running",
            "engine": "agent",
        })

    @routes.get("/scan/{scan_id}/status")
    async def scan_status(request: web.Request) -> web.Response:
        scan_id = request.match_info["scan_id"]
        scan = _scans.get(scan_id)
        if not scan:
            return web.json_response(
                {"error": "Scan not found"}, status=HTTPStatus.NOT_FOUND
            )
        # Return progress without the full host list
        return web.json_response({
            "id": scan["id"],
            "status": scan["status"],
            "total": scan.get("total", 0),
            "scanned": scan.get("scanned", 0),
            "found": scan.get("found", 0),
            "engine": "agent",
            "error": scan.get("error"),
        })

    @routes.get("/scan/{scan_id}/results")
    async def scan_results(request: web.Request) -> web.Response:
        scan_id = request.match_info["scan_id"]
        scan = _scans.get(scan_id)
        if not scan:
            return web.json_response(
                {"error": "Scan not found"}, status=HTTPStatus.NOT_FOUND
            )
        return web.json_response({
            "id": scan["id"],
            "status": scan["status"],
            "hosts": scan.get("hosts", []),
            "found": scan.get("found", 0),
            "engine": "agent",
        })

    @routes.post("/scan/{scan_id}/cancel")
    async def cancel_scan(request: web.Request) -> web.Response:
        scan_id = request.match_info["scan_id"]
        from backend.core.network_discovery import cancel_discovery
        if cancel_discovery(scan_id):
            return web.json_response({"status": "cancel_requested"})
        return web.json_response(
            {"error": "Scan not found or not running"},
            status=HTTPStatus.NOT_FOUND,
        )

    app = web.Application()
    app.add_routes(routes)

    logger.info(
        "╔══════════════════════════════════════════════════════════╗"
    )
    logger.info(
        "║  AuditForge Discovery Agent listening on %s:%d  ║",
        host, port,
    )
    logger.info(
        "║  The Docker backend will connect automatically.        ║"
    )
    logger.info(
        "╚══════════════════════════════════════════════════════════╝"
    )

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # Keep running forever
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down agent...")
    finally:
        await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AuditForge Discovery Agent — host-level network scanner"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Listen address (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=37120, help="Listen port (default: 37120)"
    )
    args = parser.parse_args()

    # Ensure the pure-Python engine is used (not Nmap routing)
    os.environ["AUDITFORGE_AGENT_MODE"] = "1"

    asyncio.run(run_server(args.host, args.port))


if __name__ == "__main__":
    main()
