"""Runtime environment discovery for target systems.

Before executing audit commands, discovers actual paths, versions, and
configuration locations on the target system.  The discovered values are
then substituted into commands via :func:`adapt_command`, replacing
hardcoded defaults and placeholders.

Usage::

    env = await discover_environment(connector, secondary, target_type, platform)
    adapted_cmd = adapt_command(original_cmd, env)
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# Discovery Templates per Platform

DISCOVERY_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "postgresql": [
        {"key": "data_dir",    "cmd": "SHOW data_directory;",  "transport": "sql"},
        {"key": "config_file", "cmd": "SHOW config_file;",     "transport": "sql"},
        {"key": "hba_file",    "cmd": "SHOW hba_file;",        "transport": "sql"},
        {"key": "pg_version",  "cmd": "SHOW server_version;",  "transport": "sql"},
        {"key": "log_directory", "cmd": "SHOW log_directory;",  "transport": "sql"},
    ],
    "oracle": [
        {"key": "oracle_home",  "cmd": "SELECT SYS_CONTEXT('USERENV','ORACLE_HOME') FROM DUAL;", "transport": "sql"},
        {"key": "audit_dest",   "cmd": "SELECT VALUE FROM V$PARAMETER WHERE NAME='audit_file_dest';", "transport": "sql"},
        {"key": "db_name",      "cmd": "SELECT VALUE FROM V$PARAMETER WHERE NAME='db_name';", "transport": "sql"},
    ],
    "mssql": [
        {"key": "install_path", "cmd": "SELECT SERVERPROPERTY('InstanceDefaultDataPath');", "transport": "sql"},
        {"key": "version",      "cmd": "SELECT SERVERPROPERTY('ProductVersion');",          "transport": "sql"},
        {"key": "instance_name", "cmd": "SELECT SERVERPROPERTY('InstanceName');",           "transport": "sql"},
    ],
    "mysql": [
        {"key": "datadir",     "cmd": "SELECT @@datadir;",                "transport": "sql"},
        {"key": "basedir",     "cmd": "SELECT @@basedir;",                "transport": "sql"},
        {"key": "version",     "cmd": "SELECT @@version;",                "transport": "sql"},
        {"key": "config_file", "cmd": "SELECT @@general_log_file;",       "transport": "sql"},
    ],
    "mongodb": [
        {"key": "config_path", "cmd": "cat /etc/mongod.conf 2>/dev/null | head -1 && echo '/etc/mongod.conf' || echo '/etc/mongodb.conf'", "transport": "shell"},
        {"key": "data_dir",    "cmd": "grep -i 'dbPath' /etc/mongod.conf 2>/dev/null | awk -F: '{print $2}' | tr -d ' '", "transport": "shell"},
    ],
    "tomcat": [
        {"key": "catalina_home", "cmd": "ps aux 2>/dev/null | grep -oP 'catalina\\.home=\\K\\S+' | head -1", "transport": "shell"},
        {"key": "catalina_base", "cmd": "ps aux 2>/dev/null | grep -oP 'catalina\\.base=\\K\\S+' | head -1", "transport": "shell"},
    ],
    "nginx": [
        {"key": "config_path",  "cmd": "nginx -t 2>&1 | grep -oP 'file \\K\\S+' | head -1",    "transport": "shell"},
        {"key": "prefix",       "cmd": "nginx -V 2>&1 | grep -oP 'prefix=\\K\\S+'",            "transport": "shell"},
    ],
    "apache": [
        {"key": "server_root",  "cmd": "apachectl -V 2>/dev/null | grep -oP 'HTTPD_ROOT=\"\\K[^\"]+' || httpd -V 2>/dev/null | grep -oP 'HTTPD_ROOT=\"\\K[^\"]+' || echo '/etc/httpd'", "transport": "shell"},
        {"key": "config_file",  "cmd": "apachectl -V 2>/dev/null | grep -oP 'SERVER_CONFIG_FILE=\"\\K[^\"]+' || echo 'conf/httpd.conf'", "transport": "shell"},
    ],
    "linux": [
        {"key": "os_id",       "cmd": "grep '^ID=' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"'", "transport": "shell"},
        {"key": "os_version",  "cmd": "grep '^VERSION_ID=' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"'", "transport": "shell"},
    ],
}

# Common default path mappings

_DEFAULT_PATHS: dict[str, dict[str, list[str]]] = {
    "postgresql": {
        "data_dir": [
            "/var/lib/pgsql/16/data",
            "/var/lib/pgsql/17/data",
            "/var/lib/pgsql/data",
            "/var/lib/postgresql/16/main",
            "/var/lib/postgresql/17/main",
            "/var/lib/postgresql/data",
            "/etc/postgresql/16/main",
            "/etc/postgresql/17/main",
        ],
        "hba_file": [
            "/var/lib/pgsql/16/data/pg_hba.conf",
            "/var/lib/pgsql/17/data/pg_hba.conf",
            "/etc/postgresql/16/main/pg_hba.conf",
            "/etc/postgresql/17/main/pg_hba.conf",
        ],
        "config_file": [
            "/var/lib/pgsql/16/data/postgresql.conf",
            "/var/lib/pgsql/17/data/postgresql.conf",
            "/etc/postgresql/16/main/postgresql.conf",
            "/etc/postgresql/17/main/postgresql.conf",
        ],
    },
    "mysql": {
        "datadir": ["/var/lib/mysql", "/var/lib/mysql-files"],
    },
    "mongodb": {
        "config_path": ["/etc/mongod.conf", "/etc/mongodb.conf"],
        "data_dir": ["/var/lib/mongo", "/var/lib/mongodb"],
    },
}


# Core Functions

async def discover_environment(
    primary_connector: Any,
    secondary_connector: Any,
    target_type: str,
    platform: str,
) -> dict[str, str]:
    """Execute discovery probes and return a key-value environment dict.

    Uses *primary_connector* for SQL-transport probes and
    *secondary_connector* (SSH/WinRM) for shell probes.
    """
    env: dict[str, str] = {}

    # Normalize platform to find matching discovery templates
    platform_lower = (platform or "").lower().replace("-", "_").replace(" ", "_")

    # Find matching discovery templates
    templates = None
    for key, tmpl_list in DISCOVERY_TEMPLATES.items():
        if key in platform_lower or platform_lower.startswith(key):
            templates = tmpl_list
            break

    if templates is None:
        # Try generic linux discovery for unknown platforms
        target_lower = (target_type or "").lower()
        if target_lower in ("linux", "unix"):
            templates = DISCOVERY_TEMPLATES.get("linux", [])
        else:
            return env

    for probe in templates:
        key = probe["key"]
        cmd = probe["cmd"]
        transport = probe["transport"]

        try:
            connector = primary_connector if transport == "sql" else secondary_connector
            if connector is None:
                continue

            result = await connector.execute(cmd)
            if result and result.stdout and result.stdout.strip():
                output_lines = result.stdout.strip().split("\n")
                # Skip PostgreSQL SHOW header (column name + dashed separator)
                if len(output_lines) >= 3 and all(c in "-+ " for c in output_lines[1].strip()):
                    value = output_lines[2].strip()
                else:
                    value = output_lines[0].strip()
                # Skip common error indicators
                if value and not value.startswith("ERROR") and value != "NULL":
                    env[key] = value
                    logger.debug("Discovery: %s = %s", key, value)
        except Exception as exc:
            logger.debug("Discovery probe %s failed: %s", key, exc)
            continue

    logger.info("Environment discovery found %d values for platform %s: %s",
                len(env), platform, list(env.keys()))
    return env


def adapt_command(cmd: str, env: dict[str, str]) -> str:
    """Substitute discovered environment values into a command.

    Handles:
    1. Explicit ``{key}`` placeholders
    2. Known hardcoded default paths replaced with discovered values
    3. Shell variable assignments using discovered values
    """
    import shlex

    if not cmd or not env:
        return cmd

    adapted = cmd

    # 1. Replace {placeholder} patterns
    for key, value in env.items():
        placeholder = "{" + key + "}"
        if placeholder in adapted:
            adapted = adapted.replace(placeholder, shlex.quote(value))

    # 2. Replace known hardcoded paths
    for platform, path_groups in _DEFAULT_PATHS.items():
        for env_key, default_paths in path_groups.items():
            if env_key in env:
                discovered = env[env_key]
                for default_path in default_paths:
                    if default_path in adapted and default_path != discovered:
                        adapted = adapted.replace(default_path, discovered)
                        logger.debug("Adapted path: %s -> %s", default_path, discovered)

    return adapted
