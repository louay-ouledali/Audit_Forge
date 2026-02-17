"""WinRM connector for Windows targets using pywinrm."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.connectors.base import BaseConnector, CommandResult

logger = logging.getLogger("auditforge.connectors.winrm")


def _try_session(winrm, endpoint: str, username: str, password: str,
                 transport: str, host: str):
    """Attempt a single WinRM session with the given transport. Returns session or raises."""
    logger.info("Trying WinRM %s auth to %s as %s", transport, endpoint, username)
    session = winrm.Session(
        endpoint,
        auth=(username, password),
        transport=transport,
        server_cert_validation="ignore",
        operation_timeout_sec=30,
        read_timeout_sec=35,
    )
    result = session.run_ps("$env:COMPUTERNAME")
    if result.status_code != 0:
        err_msg = result.std_err.decode("utf-8", errors="replace")
        raise ConnectionError(f"WinRM test command failed ({transport}): {err_msg}")
    logger.info("WinRM %s auth succeeded for %s", transport, host)
    return session


class WinRMConnector(BaseConnector):
    """Connect to Windows targets over WinRM using *pywinrm*.

    Supports both HTTP (5985) and HTTPS (5986).  When the requested port
    fails, the connector automatically retries on the *other* port so
    that targets on public-network profiles (which block AllowUnencrypted)
    still work over HTTPS without manual reconfiguration.
    """

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

        # Build ordered list of (endpoint, transports) to try.
        # HTTPS endpoints use ntlm & credssp; HTTP endpoints use ntlm & basic.
        https_endpoint = f"https://{host}:5986/wsman"
        http_endpoint = f"http://{host}:5985/wsman"
        https_transports = ["ntlm", "credssp"]
        http_transports = ["ntlm", "basic"]

        if port == 5986:
            # User explicitly chose HTTPS — try it first, fall back to HTTP
            attempts = [
                (https_endpoint, https_transports),
                (http_endpoint, http_transports),
            ]
        else:
            # Default / port 5985 — try HTTP first, then auto-fallback to HTTPS
            attempts = [
                (http_endpoint, http_transports),
                (https_endpoint, https_transports),
            ]

        def _do_connect():
            last_error: Exception | None = None
            tried: list[str] = []
            for endpoint, transports in attempts:
                for transport in transports:
                    combo = f"{transport}@{endpoint}"
                    tried.append(combo)
                    try:
                        return _try_session(
                            winrm, endpoint, username, password, transport, host,
                        )
                    except Exception as exc:
                        last_error = exc
                        logger.warning(
                            "WinRM %s to %s failed: %s", transport, endpoint, exc,
                        )
                        continue

            # --- All attempts failed ---
            raise ConnectionError(
                f"All WinRM auth methods failed for {host}. "
                f"Tried: {', '.join(tried)}. "
                f"Last error: {last_error}. "
                f"Quick-fix options:\n"
                f"  • HTTPS (recommended): on the target run:\n"
                f"      winrm quickconfig -transport:https\n"
                f"    then set the target port to 5986 in AuditForge.\n"
                f"  • HTTP (private networks only):\n"
                f"      Enable-PSRemoting -Force\n"
                f"      winrm set winrm/config/service '@{{AllowUnencrypted=\"true\"}}'\n"
            )

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
