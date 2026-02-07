"""SSH connector for Linux targets using Paramiko."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.connectors.base import BaseConnector, CommandResult

logger = logging.getLogger("auditforge.connectors.ssh")


class SSHConnector(BaseConnector):
    """Connect to Linux targets over SSH using *paramiko*."""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._host: str = ""
        self._port: int = 22

    # ------------------------------------------------------------------
    async def connect(self, target: Any) -> bool:
        try:
            import paramiko  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "paramiko is required for SSH connections. "
                "Install it with: pip install paramiko"
            ) from exc

        host = getattr(target, "ip_address", None) or getattr(target, "hostname", "")
        port = getattr(target, "port", None) or 22
        username = getattr(target, "ssh_username", None) or "root"
        password = getattr(target, "_decrypted_password", None)
        key_path = getattr(target, "ssh_key_path", None)

        self._host = host
        self._port = port

        def _do_connect():
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            kwargs: dict[str, Any] = {
                "hostname": host,
                "port": port,
                "username": username,
                "timeout": 15,
                "allow_agent": False,
                "look_for_keys": False,
            }
            if key_path:
                kwargs["key_filename"] = key_path
            elif password:
                kwargs["password"] = password
            else:
                raise ConnectionError(
                    "No credentials provided — supply either ssh_password or ssh_key_path"
                )
            client.connect(**kwargs)
            return client

        loop = asyncio.get_event_loop()
        try:
            self._client = await loop.run_in_executor(None, _do_connect)
        except Exception as exc:
            logger.error("SSH connection to %s:%s failed: %s", host, port, exc)
            raise ConnectionError(f"SSH connection failed: {exc}") from exc

        logger.info("SSH connected to %s:%s as %s", host, port, username)
        return True

    # ------------------------------------------------------------------
    async def execute(self, command: str, timeout: int = 30) -> CommandResult:
        if self._client is None:
            raise RuntimeError("Not connected — call connect() first")

        loop = asyncio.get_event_loop()
        start = time.monotonic()

        def _run():
            _stdin, _stdout, _stderr = self._client.exec_command(
                command, timeout=timeout
            )
            out = _stdout.read().decode("utf-8", errors="replace")
            err = _stderr.read().decode("utf-8", errors="replace")
            code = _stdout.channel.recv_exit_status()
            return out, err, code

        try:
            stdout, stderr, exit_code = await loop.run_in_executor(None, _run)
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.warning("SSH command failed on %s: %s", self._host, exc)
            return CommandResult(
                stdout="", stderr=str(exc), exit_code=-1, execution_time_ms=elapsed
            )

        elapsed = int((time.monotonic() - start) * 1000)
        return CommandResult(
            stdout=stdout.strip(),
            stderr=stderr.strip(),
            exit_code=exit_code,
            execution_time_ms=elapsed,
        )

    # ------------------------------------------------------------------
    async def get_system_info(self) -> dict:
        info: dict[str, str] = {}
        commands = {
            "hostname": "hostname",
            "os": "uname -s",
            "os_version": "cat /etc/os-release 2>/dev/null | head -5 || uname -r",
            "architecture": "uname -m",
            "ip": "hostname -I 2>/dev/null | awk '{print $1}' || echo unknown",
        }
        for key, cmd in commands.items():
            result = await self.execute(cmd, timeout=10)
            info[key] = result.stdout.split("\n")[0] if result.stdout else "unknown"
        return info

    # ------------------------------------------------------------------
    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._client.close)
            except Exception:
                pass
            self._client = None
            logger.info("SSH disconnected from %s", self._host)
