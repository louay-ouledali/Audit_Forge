"""Netmiko connector for network devices (Cisco, Juniper, Fortinet, etc.)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.connectors.base import BaseConnector, CommandResult

logger = logging.getLogger("auditforge.connectors.netmiko")

# Map AuditForge target_type values to netmiko device_type strings
_DEVICE_TYPE_MAP: dict[str, str] = {
    "cisco_ios": "cisco_ios",
    "cisco_nxos": "cisco_nxos",
    "cisco_asa": "cisco_asa",
    "juniper": "juniper_junos",
    "fortinet": "fortinet",
    "palo_alto": "paloalto_panos",
    "checkpoint": "checkpoint_gaia",
    "arista": "arista_eos",
    "hp_procurve": "hp_procurve",
}

# Platform-aware commands for get_system_info()
_SYSINFO_COMMANDS: dict[str, tuple[str, str]] = {
    "cisco_ios":   ("show version",              "show hostname"),
    "cisco_nxos":  ("show version",              "show hostname"),
    "cisco_asa":   ("show version",              "show hostname"),
    "juniper":     ("show system information",   "show system hostname"),
    "fortinet":    ("get system status",         "get system status"),
    "palo_alto":   ("show system info",          "show system info"),
    "checkpoint":  ("show asset system",         "show hostname"),
    "arista":      ("show version",              "show hostname"),
    "hp_procurve": ("show system-information",   "show system-information"),
}

# Cisco device types that may need enable (privilege exec) mode
_ENABLE_DEVICE_TYPES = {"cisco_ios", "cisco_nxos", "cisco_asa"}


class NetmikoConnector(BaseConnector):
    """Connect to network devices via SSH using *netmiko*."""

    def __init__(self) -> None:
        self._connection: Any | None = None
        self._host: str = ""
        self._device_type: str = ""
        self._target_type: str = ""

    # ------------------------------------------------------------------
    async def connect(self, target: Any) -> bool:
        try:
            from netmiko import ConnectHandler  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "netmiko is required for network device connections. "
                "Install it with: pip install netmiko"
            ) from exc

        host = getattr(target, "hostname", None) or getattr(target, "ip_address", "")
        port = getattr(target, "port", None) or 22
        username = getattr(target, "ssh_username", None) or "admin"
        password = getattr(target, "_decrypted_password", None)
        ssh_key_path = getattr(target, "ssh_key_path", None) or None
        raw_type = getattr(target, "target_type", "cisco_ios")
        # Use the explicit device_type column if set (e.g. when target_type="network")
        explicit_device = getattr(target, "device_type", None)
        if explicit_device:
            device_type = _DEVICE_TYPE_MAP.get(explicit_device.lower(), explicit_device.lower())
        else:
            device_type = _DEVICE_TYPE_MAP.get(raw_type.lower(), raw_type.lower())

        if not password and not ssh_key_path:
            raise ConnectionError(
                "Netmiko connector requires a password or SSH key"
            )

        self._host = host
        self._device_type = device_type
        self._target_type = raw_type.lower()

        # --- Decrypt enable password if present ---
        enable_password: str | None = None
        enable_password_enc = getattr(target, "enable_password_encrypted", None)
        if enable_password_enc:
            try:
                from backend.utils.encryption import decrypt_value
                from backend.config import settings
                enable_password = decrypt_value(
                    enable_password_enc, settings.effective_encryption_key
                )
            except Exception:
                logger.debug("Could not decrypt enable password for %s", host)

        # --- Build connection params ---
        device_params: dict[str, Any] = {
            "device_type": device_type,
            "host": host,
            "port": port,
            "username": username,
            "timeout": 15,
            "session_timeout": 60,
        }

        if ssh_key_path:
            device_params["use_keys"] = True
            device_params["key_file"] = ssh_key_path
            if password:
                device_params["password"] = password  # key passphrase
        elif password:
            device_params["password"] = password

        if enable_password:
            device_params["secret"] = enable_password

        loop = asyncio.get_running_loop()
        try:
            self._connection = await loop.run_in_executor(
                None, lambda: ConnectHandler(**device_params)
            )
        except Exception as exc:
            logger.error(
                "Netmiko connection to %s (%s) failed: %s", host, device_type, exc
            )
            raise ConnectionError(f"Network device connection failed: {exc}") from exc

        # Enter privileged exec mode for Cisco devices when enable password is set
        if enable_password and self._target_type in _ENABLE_DEVICE_TYPES:
            try:
                await loop.run_in_executor(None, self._connection.enable)
                logger.info("Netmiko entered enable mode on %s", host)
            except Exception as exc:
                logger.warning("Could not enter enable mode on %s: %s", host, exc)

        logger.info("Netmiko connected to %s (%s)", host, device_type)
        return True

    # ------------------------------------------------------------------
    async def execute(self, command: str, timeout: int = 30) -> CommandResult:
        if self._connection is None:
            raise RuntimeError("Not connected — call connect() first")

        loop = asyncio.get_running_loop()
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

        version_cmd, hostname_cmd = _SYSINFO_COMMANDS.get(
            self._target_type, ("show version", "show hostname")
        )

        result = await self.execute(version_cmd, timeout=15)
        if result.stdout:
            info["version_output"] = result.stdout[:500]

        result_host = await self.execute(hostname_cmd, timeout=10)
        info["hostname"] = (
            result_host.stdout.split("\n")[0] if result_host.stdout else "unknown"
        )
        return info

    # ------------------------------------------------------------------
    async def disconnect(self) -> None:
        if self._connection is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._connection.disconnect)
            except Exception:
                pass
            self._connection = None
            logger.info("Netmiko disconnected from %s", self._host)
