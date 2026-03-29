"""Microsoft SQL Server connector using pyodbc."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.connectors.base import BaseConnector, CommandResult

logger = logging.getLogger("auditforge.connectors.mssql")


class MSSQLConnector(BaseConnector):
    """Connect to Microsoft SQL Server using *pyodbc*."""

    def __init__(self) -> None:
        self._conn: Any | None = None
        self._host: str = ""
        self._database: str = ""

    # ------------------------------------------------------------------
    async def connect(self, target: Any) -> bool:
        try:
            import pyodbc  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "pyodbc is required for MSSQL connections. "
                "Install it with: pip install pyodbc"
            ) from exc

        host = getattr(target, "ip_address", None) or getattr(target, "hostname", "localhost")
        port = getattr(target, "port", None) or 1433
        username = getattr(target, "ssh_username", None) or "sa"
        password = getattr(target, "_decrypted_password", None)
        database = getattr(target, "db_name", None) or "master"

        self._host = host
        self._database = database

        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={host},{port};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password or ''};"
            f"Connection Timeout=15;"
        )

        def _do_connect():
            return pyodbc.connect(conn_str, timeout=15)

        loop = asyncio.get_event_loop()
        try:
            self._conn = await loop.run_in_executor(None, _do_connect)
        except Exception as exc:
            logger.error("MSSQL connection to %s:%s failed: %s", host, port, exc)
            raise ConnectionError(f"MSSQL connection failed: {exc}") from exc

        logger.info("MSSQL connected to %s:%s/%s", host, port, database)
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
                    colnames = [col[0] for col in cur.description] if cur.description else []
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
        result = await self.execute("SELECT @@VERSION", timeout=10)
        return {
            "hostname": self._host,
            "database": self._database,
            "version": result.stdout.split("\n")[-1] if result.stdout else "unknown",
            "type": "mssql",
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
            logger.info("MSSQL disconnected from %s", self._host)
