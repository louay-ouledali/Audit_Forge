#!/usr/bin/env python3
"""AuditForge Discovery Agent — Docker sidecar with host network access.

Runs as a docker-compose service with ``network_mode: host``, giving it
direct Layer 2 access to the real network — ARP, MACs, multicast, etc.

Started automatically by ``docker compose up``.

Capabilities:
  - Real MAC addresses from the host's ARP table
  - ICMP ping that finds phones, TVs, IoT
  - Multicast: mDNS (5353) + SSDP (1900) for consumer devices
  - UDP probes: NetBIOS, SNMP, DNS, NTP
  - All 47+ TCP ports with proper service labels

The backend container connects to this agent on port 37120.

Zero external dependencies — uses only Python stdlib.
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
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
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
# Background event loop for running async scans
_loop: asyncio.AbstractEventLoop | None = None


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


def _start_scan_in_loop(scan_id: str, subnet: str) -> None:
    """Schedule a scan on the background asyncio loop."""
    global _loop
    if _loop is None or _loop.is_closed():
        raise RuntimeError("Background event loop not running")
    asyncio.run_coroutine_threadsafe(_run_scan(scan_id, subnet), _loop)


class AgentHandler(BaseHTTPRequestHandler):
    """Minimal HTTP request handler for the discovery agent API."""

    def log_message(self, format, *args):
        logger.info("%s %s", self.client_address[0], format % args)

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.rstrip("/")

        if path == "/health":
            self._send_json({"status": "ok", "agent": "auditforge-discovery", "version": "2.0"})
            return

        # /scan/<id>/status
        parts = path.split("/")
        if len(parts) == 4 and parts[1] == "scan" and parts[3] == "status":
            scan_id = parts[2]
            scan = _scans.get(scan_id)
            if not scan:
                self._send_json({"error": "Scan not found"}, 404)
                return
            self._send_json({
                "id": scan["id"],
                "status": scan["status"],
                "total": scan.get("total", 0),
                "scanned": scan.get("scanned", 0),
                "found": scan.get("found", 0),
                "engine": "agent",
                "error": scan.get("error"),
            })
            return

        # /scan/<id>/results
        if len(parts) == 4 and parts[1] == "scan" and parts[3] == "results":
            scan_id = parts[2]
            scan = _scans.get(scan_id)
            if not scan:
                self._send_json({"error": "Scan not found"}, 404)
                return
            self._send_json({
                "id": scan["id"],
                "status": scan["status"],
                "hosts": scan.get("hosts", []),
                "found": scan.get("found", 0),
                "engine": "agent",
            })
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        path = self.path.rstrip("/")

        if path == "/scan":
            try:
                body = self._read_json()
            except Exception:
                self._send_json({"error": "Invalid JSON"}, 400)
                return

            subnet = body.get("subnet", "").strip()
            if not subnet:
                self._send_json({"error": "Missing 'subnet' field"}, 400)
                return

            scan_id = str(uuid.uuid4())[:8]
            _start_scan_in_loop(scan_id, subnet)
            self._send_json({"scan_id": scan_id, "status": "running", "engine": "agent"})
            return

        # /scan/<id>/cancel
        parts = path.split("/")
        if len(parts) == 4 and parts[1] == "scan" and parts[3] == "cancel":
            scan_id = parts[2]
            from backend.core.network_discovery import cancel_discovery
            if cancel_discovery(scan_id):
                self._send_json({"status": "cancel_requested"})
            else:
                self._send_json({"error": "Scan not found or not running"}, 404)
            return

        self._send_json({"error": "Not found"}, 404)


def _run_async_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Run the asyncio event loop in a background thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def main() -> None:
    global _loop

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

    # Start background asyncio loop for running scans
    _loop = asyncio.new_event_loop()
    Thread(target=_run_async_loop, args=(_loop,), daemon=True).start()

    logger.info(
        "╔══════════════════════════════════════════════════════════╗"
    )
    logger.info(
        "║  AuditForge Discovery Agent listening on %s:%d  ║",
        args.host, args.port,
    )
    logger.info(
        "║  Running on HOST — full Layer 2 network access         ║"
    )
    logger.info(
        "╚══════════════════════════════════════════════════════════╝"
    )

    server = HTTPServer((args.host, args.port), AgentHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down agent...")
    finally:
        server.server_close()
        _loop.call_soon_threadsafe(_loop.stop)


if __name__ == "__main__":
    main()
