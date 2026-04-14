"""MongoDB connector using pymongo."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from backend.connectors.base import BaseConnector, CommandResult

logger = logging.getLogger("auditforge.connectors.mongodb")


class MongoDBConnector(BaseConnector):
    """Connect to MongoDB using *pymongo*."""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._db: Any | None = None
        self._host: str = ""
        self._database: str = ""

    # ------------------------------------------------------------------
    async def connect(self, target: Any) -> bool:
        try:
            import pymongo  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "pymongo is required for MongoDB connections. "
                "Install it with: pip install pymongo"
            ) from exc

        host = getattr(target, "ip_address", None) or getattr(target, "hostname", "localhost")
        port = getattr(target, "port", None) or 27017
        username = getattr(target, "ssh_username", None)
        password = getattr(target, "_decrypted_password", None)
        database = getattr(target, "db_name", None) or "admin"

        self._host = host
        self._database = database

        def _do_connect():
            kwargs: dict[str, Any] = {
                "host": host,
                "port": int(port),
                "serverSelectionTimeoutMS": 15000,
                "connectTimeoutMS": 15000,
            }
            if username and password:
                kwargs["username"] = username
                kwargs["password"] = password
                kwargs["authSource"] = database
            client = pymongo.MongoClient(**kwargs)
            # Force a connection check
            client.admin.command("ping")
            return client

        loop = asyncio.get_running_loop()
        try:
            self._client = await loop.run_in_executor(None, _do_connect)
            self._db = self._client[database]
        except Exception as exc:
            logger.error("MongoDB connection to %s:%s failed: %s", host, port, exc)
            raise ConnectionError(f"MongoDB connection failed: {exc}") from exc

        logger.info("MongoDB connected to %s:%s/%s", host, port, database)
        return True

    # ------------------------------------------------------------------
    async def execute(self, command: str, timeout: int = 30) -> CommandResult:
        if self._client is None or self._db is None:
            raise RuntimeError("Not connected — call connect() first")

        loop = asyncio.get_running_loop()
        start = time.monotonic()

        def _run():
            try:
                result = self._execute_mongo_command(command)
                return result, ""
            except Exception as exc:
                return "", str(exc)

        try:
            stdout, stderr = await asyncio.wait_for(
                loop.run_in_executor(None, _run), timeout=timeout
            )
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - start) * 1000)
            return CommandResult(
                stdout="", stderr="Command timed out", exit_code=-1, execution_time_ms=elapsed
            )

        elapsed = int((time.monotonic() - start) * 1000)
        exit_code = 0 if not stderr else 1
        return CommandResult(
            stdout=stdout.strip() if stdout else "",
            stderr=stderr.strip() if stderr else "",
            exit_code=exit_code,
            execution_time_ms=elapsed,
        )

    def _execute_mongo_command(self, command: str) -> str:
        """Translate a mongo shell command to pymongo API call."""
        cmd = command.strip()

        # db.serverStatus()
        if re.match(r"db\.serverStatus\(\)", cmd):
            result = self._db.command("serverStatus")
            return json.dumps(result, default=str, indent=2)

        # db.version()
        if re.match(r"db\.version\(\)", cmd):
            info = self._client.server_info()
            return info.get("version", "unknown")

        # db.adminCommand({...})
        m = re.match(r"db\.adminCommand\((.+)\)", cmd, re.DOTALL)
        if m:
            cmd_doc = self._parse_mongo_doc(m.group(1))
            result = self._client.admin.command(cmd_doc)
            return json.dumps(result, default=str, indent=2)

        # db.runCommand({...})
        m = re.match(r"db\.runCommand\((.+)\)", cmd, re.DOTALL)
        if m:
            cmd_doc = self._parse_mongo_doc(m.group(1))
            result = self._db.command(cmd_doc)
            return json.dumps(result, default=str, indent=2)

        # db.getUsers()
        if re.match(r"db\.getUsers\(\)", cmd):
            result = self._db.command("usersInfo")
            return json.dumps(result, default=str, indent=2)

        # db.getRoles({showBuiltinRoles: true})
        m = re.match(r"db\.getRoles\((.+)\)", cmd, re.DOTALL)
        if m:
            result = self._db.command("rolesInfo", 1, showBuiltinRoles=True)
            return json.dumps(result, default=str, indent=2)

        # db.<collection>.find(...)
        m = re.match(r"db\.(\w+)\.find\(([^)]*)\)", cmd)
        if m:
            coll_name = m.group(1)
            filter_str = m.group(2).strip()
            filter_doc = self._parse_mongo_doc(filter_str) if filter_str else {}
            coll = self._db[coll_name]
            docs = list(coll.find(filter_doc, limit=100))
            return json.dumps(docs, default=str, indent=2)

        # db.<collection>.count() / countDocuments()
        m = re.match(r"db\.(\w+)\.(count|countDocuments)\(([^)]*)\)", cmd)
        if m:
            coll_name = m.group(1)
            filter_str = m.group(3).strip()
            filter_doc = self._parse_mongo_doc(filter_str) if filter_str else {}
            coll = self._db[coll_name]
            return str(coll.count_documents(filter_doc))

        # Fallback: try to run as a database command (safe allowlist only)
        _SAFE_COMMANDS = {
            "serverStatus", "ping", "usersInfo", "rolesInfo",
            "connectionStatus", "buildInfo", "getCmdLineOpts",
            "getParameter", "collStats", "dbStats", "hostInfo",
            "isMaster", "replSetGetStatus", "getLog",
        }
        if cmd in _SAFE_COMMANDS:
            try:
                result = self._db.command(cmd)
                return json.dumps(result, default=str, indent=2)
            except Exception as exc:
                return f"MongoDB command '{cmd}' failed: {exc}"
        return f"Unrecognized or disallowed MongoDB command: {cmd}"

    @staticmethod
    def _parse_mongo_doc(s: str) -> dict:
        """Best-effort parse of a MongoDB shell document literal to a Python dict."""
        s = s.strip()
        if not s:
            return {}
        # Replace JS-style keys (unquoted) with quoted keys
        cleaned = re.sub(r'(\w+)\s*:', r'"\1":', s)
        # Replace single quotes with double quotes
        cleaned = cleaned.replace("'", '"')
        # Handle JS true/false/null
        cleaned = cleaned.replace("true", "true").replace("false", "false").replace("null", "null")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Return as a simple command name if it's a single word
            if re.match(r"^\w+$", s):
                return {s: 1}
            raise ValueError(f"Cannot parse MongoDB document literal: {s[:100]}")

    # ------------------------------------------------------------------
    async def get_system_info(self) -> dict:
        result = await self.execute("db.version()", timeout=10)
        return {
            "hostname": self._host,
            "database": self._database,
            "version": result.stdout if result.stdout else "unknown",
            "type": "mongodb",
        }

    # ------------------------------------------------------------------
    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._client.close)
            except Exception:
                pass
            self._client = None
            self._db = None
            logger.info("MongoDB disconnected from %s", self._host)
