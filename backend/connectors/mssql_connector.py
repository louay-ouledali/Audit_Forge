"""Microsoft SQL Server connector using pyodbc (with pymssql fallback)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.connectors.base import BaseConnector, CommandResult

logger = logging.getLogger("auditforge.connectors.mssql")

_ODBC_DRIVERS = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server",
]


def _available_odbc_driver() -> str | None:
    """Return the first available SQL Server ODBC driver name, or None."""
    try:
        import pyodbc  # type: ignore[import-untyped]
        installed = pyodbc.drivers()
        for drv in _ODBC_DRIVERS:
            if drv in installed:
                return drv
    except Exception:
        pass
    return None


class MSSQLConnector(BaseConnector):
    """Connect to Microsoft SQL Server using pyodbc or pymssql."""

    def __init__(self) -> None:
        self._conn: Any | None = None
        self._host: str = ""
        self._database: str = ""
        self._backend: str = ""  # "pyodbc" or "pymssql"

    # ------------------------------------------------------------------
    async def connect(self, target: Any) -> bool:
        host = getattr(target, "ip_address", None) or getattr(target, "hostname", "localhost")
        port = getattr(target, "port", None) or 1433
        username = getattr(target, "ssh_username", None) or "sa"
        password = getattr(target, "_decrypted_password", None)
        database = getattr(target, "db_name", None) or "master"
        verify_tls = getattr(target, "verify_tls", True)

        self._host = host
        self._database = database

        odbc_driver = _available_odbc_driver()
        loop = asyncio.get_running_loop()

        if odbc_driver:
            try:
                import pyodbc  # type: ignore[import-untyped]
                trust_cert = "yes" if not verify_tls else "no"
                conn_str = (
                    f"DRIVER={{{odbc_driver}}};"
                    f"SERVER={host},{port};"
                    f"DATABASE={database};"
                    f"UID={username};"
                    f"PWD={(password or '').replace('}', '}}').replace(';', '')};"
                    f"Connection Timeout=15;"
                    f"TrustServerCertificate={trust_cert};"
                )
                def _do_pyodbc():
                    return pyodbc.connect(conn_str, timeout=15)
                self._conn = await loop.run_in_executor(None, _do_pyodbc)
                self._backend = "pyodbc"
                logger.info("MSSQL connected via pyodbc (%s) to %s:%s/%s", odbc_driver, host, port, database)
                return True
            except Exception as exc:
                logger.warning("pyodbc connect failed (%s), trying pymssql: %s", odbc_driver, exc)

        # Fallback: pymssql
        try:
            import pymssql  # type: ignore[import-untyped]
            def _do_pymssql():
                return pymssql.connect(
                    server=host, port=str(port), user=username,
                    password=password or "", database=database, timeout=15,
                )
            self._conn = await loop.run_in_executor(None, _do_pymssql)
            self._backend = "pymssql"
            logger.info("MSSQL connected via pymssql to %s:%s/%s", host, port, database)
            return True
        except ImportError:
            raise ConnectionError(
                "MSSQL connection failed: no suitable driver found. "
                "Install 'ODBC Driver 17 for SQL Server' or run: pip install pymssql"
            )
        except Exception as exc:
            logger.error("MSSQL pymssql connect to %s:%s failed: %s", host, port, exc)
            raise ConnectionError(f"MSSQL connection failed: {exc}") from exc

    # ------------------------------------------------------------------
    async def execute(self, command: str, timeout: int = 30) -> CommandResult:
        if self._conn is None:
            raise RuntimeError("Not connected — call connect() first")

        loop = asyncio.get_running_loop()
        start = time.monotonic()

        def _run():
            from backend.connectors.sql_guard import assert_readonly
            assert_readonly(command)
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
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._conn.close)
            except Exception:
                pass
            self._conn = None
            logger.info("MSSQL disconnected from %s", self._host)
