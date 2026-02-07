"""WinRM connector for Windows targets using pywinrm."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.connectors.base import BaseConnector, CommandResult

logger = logging.getLogger("auditforge.connectors.winrm")


class WinRMConnector(BaseConnector):
    """Connect to Windows targets over WinRM using *pywinrm*."""

    def __init__(self) -> None:
        self._session: Any | None = None
        self._host: str = ""
        self._port: int = 5985

    # ------------------------------------------------------------------
    async def connect(self, target: Any) -> bool:
        try:
            import winrm  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "pywinrm is required for WinRM connections. "
                "Install it with: pip install pywinrm"
            ) from exc

        host = getattr(target, "ip_address", None) or getattr(target, "hostname", "")
        port = getattr(target, "port", None) or 5985
        username = getattr(target, "ssh_username", None) or "Administrator"
        password = getattr(target, "_decrypted_password", None)

        if not password:
            raise ConnectionError("WinRM requires a password")

        self._host = host
        self._port = port

        scheme = "https" if port == 5986 else "http"
        endpoint = f"{scheme}://{host}:{port}/wsman"

        def _do_connect():
            session = winrm.Session(
                endpoint,
                auth=(username, password),
                transport="ntlm",
                server_cert_validation="ignore",
                operation_timeout_sec=30,
                read_timeout_sec=35,
            )
            # Verify connectivity with a lightweight command
            result = session.run_ps("$env:COMPUTERNAME")
            if result.status_code != 0:
                raise ConnectionError(
                    f"WinRM test command failed: {result.std_err.decode('utf-8', errors='replace')}"
                )
            return session

        loop = asyncio.get_event_loop()
        try:
            self._session = await loop.run_in_executor(None, _do_connect)
        except Exception as exc:
            logger.error("WinRM connection to %s:%s failed: %s", host, port, exc)
            raise ConnectionError(f"WinRM connection failed: {exc}") from exc

        logger.info("WinRM connected to %s:%s", host, port)
        return True

    # ------------------------------------------------------------------
    async def execute(self, command: str, timeout: int = 30) -> CommandResult:
        if self._session is None:
            raise RuntimeError("Not connected — call connect() first")

        loop = asyncio.get_event_loop()
        start = time.monotonic()

        def _run():
            return self._session.run_ps(command)

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _run), timeout=timeout
            )
            stdout = result.std_out.decode("utf-8", errors="replace").strip()
            stderr = result.std_err.decode("utf-8", errors="replace").strip()
            exit_code = result.status_code
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
            logger.warning("WinRM command failed on %s: %s", self._host, exc)
            return CommandResult(
                stdout="", stderr=str(exc), exit_code=-1, execution_time_ms=elapsed
            )

        elapsed = int((time.monotonic() - start) * 1000)
        return CommandResult(
            stdout=stdout, stderr=stderr, exit_code=exit_code, execution_time_ms=elapsed
        )

    # ------------------------------------------------------------------
    async def get_system_info(self) -> dict:
        info: dict[str, str] = {}
        commands = {
            "hostname": "$env:COMPUTERNAME",
            "os": "(Get-CimInstance Win32_OperatingSystem).Caption",
            "os_version": "(Get-CimInstance Win32_OperatingSystem).Version",
            "architecture": "$env:PROCESSOR_ARCHITECTURE",
            "ip": "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.InterfaceAlias -ne 'Loopback Pseudo-Interface 1'} | Select-Object -First 1).IPAddress",
        }
        for key, cmd in commands.items():
            result = await self.execute(cmd, timeout=15)
            info[key] = result.stdout.split("\n")[0] if result.stdout else "unknown"
        return info

    # ------------------------------------------------------------------
    async def disconnect(self) -> None:
        # pywinrm sessions are stateless HTTP — no persistent connection to close.
        self._session = None
        logger.info("WinRM session for %s released", self._host)
