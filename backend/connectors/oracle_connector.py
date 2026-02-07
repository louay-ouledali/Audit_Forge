"""Oracle Database connector using oracledb."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.connectors.base import BaseConnector, CommandResult

logger = logging.getLogger("auditforge.connectors.oracle")


class OracleConnector(BaseConnector):
    """Connect to Oracle Database using *oracledb* (thin mode)."""

    def __init__(self) -> None:
        self._conn: Any | None = None
        self._host: str = ""
        self._service_name: str = ""

    # ------------------------------------------------------------------
    async def connect(self, target: Any) -> bool:
        try:
            import oracledb  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "oracledb is required for Oracle connections. "
                "Install it with: pip install oracledb"
            ) from exc

        host = getattr(target, "ip_address", None) or getattr(target, "hostname", "localhost")
        port = getattr(target, "port", None) or 1521
        username = getattr(target, "ssh_username", None) or "system"
        password = getattr(target, "_decrypted_password", None)
        service_name = getattr(target, "os_details", None) or "ORCL"

        self._host = host
        self._service_name = service_name

        dsn = f"{host}:{port}/{service_name}"

        def _do_connect():
            return oracledb.connect(user=username, password=password or "", dsn=dsn)

        loop = asyncio.get_event_loop()
        try:
            self._conn = await loop.run_in_executor(None, _do_connect)
        except Exception as exc:
            logger.error("Oracle connection to %s failed: %s", dsn, exc)
            raise ConnectionError(f"Oracle connection failed: {exc}") from exc

        logger.info("Oracle connected to %s", dsn)
        return True

    # ------------------------------------------------------------------
    async def execute(self, command: str, timeout: int = 30) -> CommandResult:
        if self._conn is None:
            raise RuntimeError("Not connected — call connect() first")

        loop = asyncio.get_event_loop()
        start = time.monotonic()

        def _run():
            cur = self._conn.cursor()
            try:
                cur.execute(command)
                try:
                    rows = cur.fetchall()
                    colnames = [desc[0] for desc in cur.description] if cur.description else []
                    lines = ["\t".join(str(c) for c in row) for row in rows]
                    if colnames:
                        header = "\t".join(colnames)
                        return header + "\n" + "\n".join(lines), ""
                    return "\n".join(lines), ""
                except Exception:
                    return f"Statement executed — {cur.rowcount} rows affected", ""
            except Exception as exc:
                return "", str(exc)
            finally:
                cur.close()

        try:
            stdout, stderr = await asyncio.wait_for(
                loop.run_in_executor(None, _run), timeout=timeout
            )
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - start) * 1000)
            return CommandResult(
                stdout="", stderr="Query timed out", exit_code=-1, execution_time_ms=elapsed
            )

        elapsed = int((time.monotonic() - start) * 1000)
        exit_code = 0 if not stderr else 1
        return CommandResult(
            stdout=stdout.strip(),
            stderr=stderr.strip(),
            exit_code=exit_code,
            execution_time_ms=elapsed,
        )

    # ------------------------------------------------------------------
    async def get_system_info(self) -> dict:
        result = await self.execute("SELECT banner FROM v$version WHERE ROWNUM = 1", timeout=10)
        return {
            "hostname": self._host,
            "service_name": self._service_name,
            "version": result.stdout.split("\n")[-1] if result.stdout else "unknown",
            "type": "oracle",
        }

    # ------------------------------------------------------------------
    async def disconnect(self) -> None:
        if self._conn is not None:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._conn.close)
            except Exception:
                pass
            self._conn = None
            logger.info("Oracle disconnected from %s", self._host)
