"""Netmiko connector for network devices (Cisco, Juniper, Fortinet, etc.)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.connectors.base import BaseConnector, CommandResult

logger = logging.getLogger("auditforge.connectors.netmiko")

# Map AditForge target_type values to netmiko device_type strings
_DEVICE_TYPE_MAP: dict[str, str] = {
    "cisco_ios": "cisco_ios",
    "cisco_nxos": "cisco_nxos",
    "cisco_asa": "cisco_asa",
    "juniper": "juniper_junos",
    "fortinet": "fortinet",
    "palo_alto": "paloalto_panos",
    "arista": "arista_eos",
    "hp_procurve": "hp_procurve",
}


class NetmikoConnector(BaseConnector):
    """Connect to network devices via SSH using *netmiko*."""

    def __init__(self) -> None:
        self._connection: Any | None = None
        self._host: str = ""
        self._device_type: str = ""

    # ------------------------------------------------------------------
    async def connect(self, target: Any) -> bool:
        try:
            from netmiko import ConnectHandler  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "netmiko is required for network device connections. "
                "Install it with: pip install netmiko"
            ) from exc

        host = getattr(target, "ip_address", None) or getattr(target, "hostname", "")
        port = getattr(target, "port", None) or 22
        username = getattr(target, "ssh_username", None) or "admin"
        password = getattr(target, "_decrypted_password", None)
        raw_type = getattr(target, "target_type", "cisco_ios")
        device_type = _DEVICE_TYPE_MAP.get(raw_type.lower(), raw_type.lower())

        if not password:
            raise ConnectionError("Netmiko connector requires a password")

        self._host = host
        self._device_type = device_type

        device_params: dict[str, Any] = {
            "device_type": device_type,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "timeout": 15,
            "session_timeout": 60,
        }

        loop = asyncio.get_event_loop()
        try:
            self._connection = await loop.run_in_executor(
                None, lambda: ConnectHandler(**device_params)
            )
        except Exception as exc:
            logger.error(
                "Netmiko connection to %s (%s) failed: %s", host, device_type, exc
            )
            raise ConnectionError(f"Network device connection failed: {exc}") from exc

        logger.info("Netmiko connected to %s (%s)", host, device_type)
        return True

    # ------------------------------------------------------------------
    async def execute(self, command: str, timeout: int = 30) -> CommandResult:
        if self._connection is None:
            raise RuntimeError("Not connected — call connect() first")

        loop = asyncio.get_event_loop()
        start = time.monotonic()

        def _run():
            return self._connection.send_command(
                command, read_timeout=timeout
            )

        try:
            output = await asyncio.wait_for(
                loop.run_in_executor(None, _run), timeout=timeout + 5
            )
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - start) * 1000)
            return CommandResult(
                stdout="",
                stderr="Command timed out",
                exit_code=-1,
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.warning("Netmiko command failed on %s: %s", self._host, exc)
            return CommandResult(
                stdout="", stderr=str(exc), exit_code=-1, execution_time_ms=elapsed
            )

        elapsed = int((time.monotonic() - start) * 1000)
        # Network devices don't return exit codes — treat non-empty output as success
        return CommandResult(
            stdout=output.strip(),
            stderr="",
            exit_code=0,
            execution_time_ms=elapsed,
        )

    # ------------------------------------------------------------------
    async def get_system_info(self) -> dict:
        info: dict[str, str] = {"device_type": self._device_type}
        result = await self.execute("show version", timeout=15)
        if result.stdout:
            info["version_output"] = result.stdout[:500]
        result_host = await self.execute("show hostname", timeout=10)
        info["hostname"] = (
            result_host.stdout.split("\n")[0] if result_host.stdout else "unknown"
        )
        return info

    # ------------------------------------------------------------------
    async def disconnect(self) -> None:
        if self._connection is not None:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._connection.disconnect)
            except Exception:
                pass
            self._connection = None
            logger.info("Netmiko disconnected from %s", self._host)
