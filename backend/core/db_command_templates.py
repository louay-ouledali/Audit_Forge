"""Deterministic command templates for database CIS benchmark rules.

Supplements the main ``command_templates.py`` with platform-specific
template chains for PostgreSQL, Oracle, MSSQL, MySQL, and MongoDB.
Each template extracts parameters from the CIS rule text and builds
a precise audit command + comparison expression, bypassing the LLM.

The public entry point is ``match_db_template(rule, platform)``.
"""

from __future__ import annotations

import re
from typing import Any


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _result(
    audit_command: str,
    expected_output_regex: str,
    expected_output_description: str = "",
    command_transport: str = "sql",
    remediation_command: str = "",
    remediation_description: str = "",
) -> dict[str, str]:
    """Build a template result dict matching the LLM output contract."""
    return {
        "audit_command": audit_command,
        "expected_output_regex": expected_output_regex,
        "expected_output_description": expected_output_description,
        "command_transport": command_transport,
        "remediation_command": remediation_command,
        "remediation_description": remediation_description,
    }


def _extract_quoted(text: str) -> str | None:
    """Extract the first single-quoted value from *text*."""
    m = re.search(r"'([^']+)'", text)
    return m.group(1) if m else None


def _text(rule: dict[str, Any]) -> str:
    """Combine title + description + audit text for matching."""
    parts = [
        rule.get("title") or "",
        rule.get("description") or "",
        rule.get("audit_description_raw") or "",
    ]
    return " ".join(parts)


def _title(rule: dict[str, Any]) -> str:
    return (rule.get("title") or "").strip()


def _title_lower(rule: dict[str, Any]) -> str:
    return _title(rule).lower()


# ═══════════════════════════════════════════════════════════════════
# PostgreSQL Templates
# ═══════════════════════════════════════════════════════════════════

# Map CIS titles / keywords → PostgreSQL setting name
_PG_SHOW_MAP: dict[str, str] = {
    "log_connections": "log_connections",
    "log_disconnections": "log_disconnections",
    "log_error_verbosity": "log_error_verbosity",
    "log_hostname": "log_hostname",
    "log_line_prefix": "log_line_prefix",
    "log_statement": "log_statement",
    "log_timezone": "log_timezone",
    "logging_collector": "logging_collector",
    "log_directory": "log_directory",
    "log_filename": "log_filename",
    "log_file_mode": "log_file_mode",
    "log_truncate_on_rotation": "log_truncate_on_rotation",
    "log_rotation_age": "log_rotation_age",
    "log_rotation_size": "log_rotation_size",
    "log_destination": "log_destination",
    "log_min_messages": "log_min_messages",
    "log_min_error_statement": "log_min_error_statement",
    "log_min_duration_statement": "log_min_duration_statement",
    "log_replication_commands": "log_replication_commands",
    "debug_print_parse": "debug_print_parse",
    "debug_print_rewritten": "debug_print_rewritten",
    "debug_print_plan": "debug_print_plan",
    "debug_pretty_print": "debug_pretty_print",
    "syslog_facility": "syslog_facility",
    "syslog_sequence_numbers": "syslog_sequence_numbers",
    "syslog_split_messages": "syslog_split_messages",
    "syslog_ident": "syslog_ident",
    "shared_preload_libraries": "shared_preload_libraries",
    "ssl": "ssl",
    "ssl_min_protocol_version": "ssl_min_protocol_version",
    "ssl_cert_file": "ssl_cert_file",
    "ssl_key_file": "ssl_key_file",
    "ssl_ca_file": "ssl_ca_file",
    "ssl_crl_file": "ssl_crl_file",
    "password_encryption": "password_encryption",
    "listen_addresses": "listen_addresses",
    "work_mem": "work_mem",
    "maintenance_work_mem": "maintenance_work_mem",
    "server_version": "server_version",
    "connection_throttling": "connection_throttle.enable",
    "pgaudit.log": "pgaudit.log",
    "pgaudit.log_catalog": "pgaudit.log_catalog",
    "pgaudit.log_parameter": "pgaudit.log_parameter",
    "pgaudit.log_statement_once": "pgaudit.log_statement_once",
    "pgaudit.role": "pgaudit.role",
}


def _try_pg_show_setting(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match PostgreSQL rules that check a GUC setting via SHOW."""
    text = _text(rule).lower()
    title = _title(rule)

    # Method 1: Look for a quoted setting name in the title (e.g., "'log_connections' is enabled")
    quoted = _extract_quoted(title)
    if quoted:
        setting = quoted.lower().replace(" ", "_")
        if setting in _PG_SHOW_MAP:
            setting_name = _PG_SHOW_MAP[setting]
            expr = _pg_infer_expression(title, setting_name)
            return _result(
                audit_command=f"SHOW {setting_name};",
                expected_output_regex=expr,
                expected_output_description=f"PostgreSQL setting {setting_name}",
            )

    # Method 2: Scan text for known setting names
    for keyword, setting_name in _PG_SHOW_MAP.items():
        if keyword in text:
            # Extra check: the setting name should be prominent, not just a passing mention
            title_l = _title_lower(rule)
            if keyword in title_l or f"'{keyword}'" in text:
                expr = _pg_infer_expression(title, setting_name)
                return _result(
                    audit_command=f"SHOW {setting_name};",
                    expected_output_regex=expr,
                    expected_output_description=f"PostgreSQL setting {setting_name}",
                )

    # Method 3: If the existing audit_command is already a SHOW command,
    # validate the setting name and adopt it
    cmd = (rule.get("audit_command") or "").strip()
    m = re.match(r'^(?:SHOW|show)\s+(\S+?)\s*;?\s*$', cmd)
    if m:
        setting_name = m.group(1).lower()
        # Accept any valid PostgreSQL GUC name (word chars + dots)
        if re.match(r'^[a-z_][a-z0-9_.]*$', setting_name):
            expr = _pg_infer_expression(title, setting_name)
            return _result(
                audit_command=f"SHOW {setting_name};",
                expected_output_regex=expr,
                expected_output_description=f"PostgreSQL setting {setting_name}",
            )

    return None


def _pg_infer_expression(title: str, setting_name: str) -> str:
    """Infer the expected expression from the CIS rule title."""
    tl = title.lower()

    # "is enabled" / "is disabled" patterns
    if "is enabled" in tl or "is set to 'on'" in tl:
        return "==on"
    if "is disabled" in tl or "is set to 'off'" in tl:
        return "==off"

    # "is set correctly" / "is configured" → non-empty check
    if "is set correctly" in tl or "is configured" in tl:
        return "not_empty"

    # "is not" patterns
    if "is not" in tl:
        return "not_empty"

    # Version checks
    if "version" in setting_name or "patch" in tl:
        return "not_empty"

    # Shared libraries containing something
    if "pgaudit" in tl or "audit extension" in tl:
        return "contains:pgaudit"
    if "passwordcheck" in tl or "password complexity" in tl:
        return "contains:passwordcheck"

    # SSL
    if "tls" in tl and ("disabled" in tl or "1.0" in tl or "1.1" in tl):
        return "contains:TLSv1.2"
    if "ssl" in tl and "enabled" in tl:
        return "==on"

    return "not_empty"


def _try_pg_select_setting(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match PostgreSQL rules querying pg_settings view."""
    text = _text(rule).lower()
    if "pg_settings" not in text and "pg_catalog" not in text:
        return None

    # Try to extract the setting name from quoted text in title
    title = _title(rule)
    quoted = _extract_quoted(title)
    if not quoted:
        return None

    setting = quoted.lower()
    expr = _pg_infer_expression(title, setting)
    return _result(
        audit_command=f"SELECT setting FROM pg_settings WHERE name = '{setting}';",
        expected_output_regex=expr,
        expected_output_description=f"PostgreSQL pg_settings value for {setting}",
    )


def _try_pg_roles(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match PostgreSQL rules about user roles and privileges."""
    text = _text(rule).lower()
    title = _title_lower(rule)

    # Superuser checks
    if "superuser" in title and ("role" in title or "user" in title):
        return _result(
            audit_command="SELECT rolname FROM pg_roles WHERE rolsuper = true;",
            expected_output_regex="contains:postgres",
            expected_output_description="Only expected superusers should be listed",
        )

    # "ensure no user has" createdb / createrole
    if "createdb" in title and ("only" in title or "superuser" in title or "restrict" in title or "ensure" in title):
        return _result(
            audit_command="SELECT rolname FROM pg_roles WHERE rolcreatedb = true;",
            expected_output_regex="not_empty",
            expected_output_description="Only expected users should have CREATEDB privilege",
        )

    if "createrole" in title and ("only" in title or "superuser" in title or "restrict" in title or "ensure" in title):
        return _result(
            audit_command="SELECT rolname FROM pg_roles WHERE rolcreaterole = true;",
            expected_output_regex="not_empty",
            expected_output_description="Only expected users should have CREATEROLE privilege",
        )

    # Replication privilege
    if "replication" in title and ("role" in title or "user" in title or "privilege" in title):
        return _result(
            audit_command="SELECT rolname FROM pg_roles WHERE rolreplication = true;",
            expected_output_regex="not_empty",
            expected_output_description="Only expected users should have REPLICATION privilege",
        )

    # Login permission
    if "login" in title and "role" in title and ("direct" in title or "restrict" in title):
        return _result(
            audit_command="SELECT rolname FROM pg_roles WHERE rolcanlogin = true;",
            expected_output_regex="not_empty",
            expected_output_description="Only authorized roles should have LOGIN privilege",
        )

    return None


def _try_pg_hba(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match PostgreSQL pg_hba.conf rules."""
    text = _text(rule).lower()
    if "pg_hba" not in text and "host-based" not in text and "hba" not in text:
        return None

    title = _title_lower(rule)

    # Authentication method checks (md5, scram, trust, etc.)
    if "trust" in title and ("reject" in title or "no" in title or "not" in title or "disable" in title):
        return _result(
            audit_command="SELECT COUNT(*) FROM pg_hba_file_rules WHERE auth_method = 'trust';",
            expected_output_regex="==0",
            expected_output_description="No trust authentication entries should exist",
        )

    if "password" in title or "encryption" in title or "scram" in title:
        return _result(
            audit_command="SHOW password_encryption;",
            expected_output_regex="==scram-sha-256",
            expected_output_description="Password encryption should use scram-sha-256",
        )

    # Generic hba check
    if "hba" in title or "host-based" in title:
        return _result(
            audit_command="SELECT type, database, user_name, address, auth_method FROM pg_hba_file_rules;",
            expected_output_regex="not_empty",
            expected_output_description="Review pg_hba.conf entries for appropriate authentication",
        )

    return None


def _try_pg_extension(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match PostgreSQL extension checks."""
    text = _text(rule).lower()
    if "extension" not in text and "contrib" not in text:
        return None

    title = _title_lower(rule)

    if "pgaudit" in title or "audit" in title:
        return _result(
            audit_command="SHOW shared_preload_libraries;",
            expected_output_regex="contains:pgaudit",
            expected_output_description="pgAudit extension should be loaded",
        )

    if "extension" in title and ("available" in title or "installed" in title):
        return _result(
            audit_command="SELECT extname, extversion FROM pg_extension ORDER BY extname;",
            expected_output_regex="not_empty",
            expected_output_description="Review installed extensions for unauthorized packages",
        )

    return None


def _try_pg_file_perm(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match PostgreSQL data directory / file permission rules."""
    text = _text(rule).lower()
    title = _title_lower(rule)

    if "data cluster" in title and "initialized" in title:
        return _result(
            audit_command="stat -c '%a %U %G' $(SHOW data_directory) 2>/dev/null || stat -c '%a %U %G' /var/lib/pgsql/*/data/ 2>/dev/null | head -1",
            expected_output_regex="contains:700",
            expected_output_description="Data directory should have mode 700",
            command_transport="shell",
        )

    if "file permissions" in title and "data" in text:
        return _result(
            audit_command="stat -c '%a' /var/lib/pgsql/*/data/ 2>/dev/null || stat -c '%a' /var/lib/postgresql/*/main/ 2>/dev/null | head -1",
            expected_output_regex="<=0700",
            expected_output_description="Data directory permission bitmask",
            command_transport="shell",
        )

    return None


# PostgreSQL template chain — tried in order, first match wins
_PG_TEMPLATES = [
    _try_pg_show_setting,
    _try_pg_select_setting,
    _try_pg_roles,
    _try_pg_hba,
    _try_pg_extension,
    _try_pg_file_perm,
]


# ═══════════════════════════════════════════════════════════════════
# MSSQL Templates
# ═══════════════════════════════════════════════════════════════════

# Map of common sys.configurations option names to their expected values
_MSSQL_SYS_CONFIG_RULES: dict[str, tuple[str, str]] = {
    "ad hoc distributed queries":     ("==0", "should be disabled"),
    "clr enabled":                    ("==0", "should be disabled"),
    "clr strict security":            ("==1", "should be enabled"),
    "cross db ownership chaining":    ("==0", "should be disabled"),
    "database mail xps":              ("==0", "should be disabled"),
    "ole automation procedures":      ("==0", "should be disabled"),
    "remote access":                  ("==0", "should be disabled"),
    "remote admin connections":       ("==0", "should be disabled unless clustered"),
    "scan for startup procs":         ("==0", "should be disabled"),
    "xp_cmdshell":                    ("==0", "should be disabled"),
    "default trace enabled":          ("==1", "should be enabled"),
    "external scripts enabled":       ("==0", "should be disabled"),
    "hadoop connectivity":            ("==0", "should be disabled"),
    "common criteria compliance enabled": ("==0", "unless required"),
}


def _try_mssql_sys_config(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MSSQL rules checking sys.configurations settings."""
    text = _text(rule).lower()
    if "sys.configurations" not in text and "server configuration" not in text.lower():
        # Match by title pattern: "'<option>' Server Configuration Option is set to '<value>'"
        pass

    title = _title(rule)
    quoted = _extract_quoted(title)
    if not quoted:
        return None

    config_name = quoted.strip()
    config_lower = config_name.lower()

    # Lookup known config
    if config_lower in _MSSQL_SYS_CONFIG_RULES:
        expr, desc = _MSSQL_SYS_CONFIG_RULES[config_lower]
    else:
        # Infer from title
        tl = _title_lower(rule)
        if "disabled" in tl or "is set to '0'" in tl or "set to 0" in tl:
            expr, desc = "==0", "should be disabled (0)"
        elif "enabled" in tl or "is set to '1'" in tl or "set to 1" in tl:
            expr, desc = "==1", "should be enabled (1)"
        else:
            return None

    return _result(
        audit_command=f"SELECT CAST(value as int) as value_configured FROM sys.configurations WHERE name = '{config_name}';",
        expected_output_regex=expr,
        expected_output_description=f"{config_name} {desc}",
    )


def _try_mssql_server_principals(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MSSQL rules about login accounts (sys.server_principals)."""
    title = _title_lower(rule)
    text = _text(rule).lower()

    # 'sa' login disabled
    if "'sa'" in title and "disabled" in title:
        return _result(
            audit_command="SELECT is_disabled FROM sys.server_principals WHERE sid = 0x01;",
            expected_output_regex="==1",
            expected_output_description="sa account should be disabled (is_disabled = 1)",
        )

    # 'sa' login renamed
    if "'sa'" in title and "renamed" in title:
        return _result(
            audit_command="SELECT name FROM sys.server_principals WHERE sid = 0x01;",
            expected_output_regex="!=sa",
            expected_output_description="sa account should be renamed to something other than 'sa'",
        )

    # No login with name 'sa'
    if "no login" in title and "'sa'" in title:
        return _result(
            audit_command="SELECT COUNT(*) FROM sys.server_principals WHERE name = 'sa';",
            expected_output_regex="==0",
            expected_output_description="No login should exist with name 'sa'",
        )

    # CONNECT permission for guest
    if "guest" in title and "connect" in title:
        return _result(
            audit_command=(
                "SELECT COUNT(*) FROM sys.database_permissions dp "
                "JOIN sys.database_principals pr ON dp.grantee_principal_id = pr.principal_id "
                "WHERE pr.name = 'guest' AND dp.permission_name = 'CONNECT' "
                "AND dp.state IN ('G','W') AND DB_NAME() NOT IN ('master','tempdb','msdb');"
            ),
            expected_output_regex="==0",
            expected_output_description="Guest CONNECT permission should not be granted",
        )

    # Orphaned users
    if "orphaned" in title and "user" in title:
        return _result(
            audit_command="SELECT COUNT(*) FROM sys.database_principals WHERE type IN ('S','U','G') AND sid NOT IN (SELECT sid FROM sys.server_principals) AND name NOT IN ('dbo','guest','INFORMATION_SCHEMA','sys','MS_DataCollectorInternalUser');",
            expected_output_regex="==0",
            expected_output_description="No orphaned users should exist",
        )

    # SYSADMIN role limited
    if "sysadmin" in title and ("limit" in title or "restriction" in title):
        return _result(
            audit_command="SELECT COUNT(*) FROM master.sys.server_principals WHERE IS_SRVROLEMEMBER('sysadmin',name) = 1 AND name NOT IN ('NT SERVICE\\MSSQLSERVER','NT SERVICE\\SQLSERVERAGENT','sa');",
            expected_output_regex="==0",
            expected_output_description="Only expected accounts should have sysadmin role",
        )

    return None


def _try_mssql_database_settings(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MSSQL rules about database-level settings (sys.databases)."""
    title = _title_lower(rule)

    # Trustworthy
    if "trustworthy" in title:
        return _result(
            audit_command="SELECT COUNT(*) FROM sys.databases WHERE is_trustworthy_on = 1 AND name != 'msdb';",
            expected_output_regex="==0",
            expected_output_description="No databases should have TRUSTWORTHY ON except msdb",
        )

    # AUTO_CLOSE on contained databases
    if "auto_close" in title and "contained" in title:
        return _result(
            audit_command="SELECT COUNT(*) FROM sys.databases WHERE containment <> 0 AND is_auto_close_on = 1;",
            expected_output_regex="==0",
            expected_output_description="No contained databases should have AUTO_CLOSE ON",
        )

    # Database encryption (TDE)
    if "encrypt" in title and "database" in title and "transparent" not in title:
        return _result(
            audit_command="SELECT COUNT(*) FROM sys.databases WHERE is_encrypted = 0 AND name NOT IN ('master','tempdb','model','msdb');",
            expected_output_regex="==0",
            expected_output_description="All user databases should be encrypted",
        )

    return None


def _try_mssql_audit(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MSSQL audit-related rules."""
    title = _title_lower(rule)
    text = _text(rule).lower()

    # Server audit specification
    if "server audit" in title and ("specification" in title or "enabled" in title):
        return _result(
            audit_command="SELECT COUNT(*) FROM sys.server_audits WHERE is_state_enabled = 1;",
            expected_output_regex=">=1",
            expected_output_description="At least one server audit should be enabled",
        )

    # Login auditing
    if "login audit" in title or ("login" in title and "failed" in title and "audit" in text):
        return _result(
            audit_command="SELECT CAST(value_data AS int) FROM sys.configurations WHERE name = 'login auditing';",
            expected_output_regex=">=2",
            expected_output_description="Login auditing should capture failed logins (2) or all logins (3)",
        )

    # SQL Server error log files
    if "error log" in title and ("number" in title or "files" in title):
        return _result(
            audit_command="EXEC xp_instance_regread N'HKEY_LOCAL_MACHINE', N'Software\\Microsoft\\MSSQLServer\\MSSQLServer', N'NumErrorLogs';",
            expected_output_regex=">=12",
            expected_output_description="Number of error log files should be >= 12",
        )

    return None


def _try_mssql_version(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MSSQL version/update rules."""
    title = _title_lower(rule)

    if "latest" in title and ("update" in title or "patch" in title or "cumulative" in title):
        return _result(
            audit_command="SELECT SERVERPROPERTY('ProductVersion') AS ProductVersion;",
            expected_output_regex="not_empty",
            expected_output_description="SQL Server version should be current",
        )

    return None


def _try_mssql_existing_sql(rule: dict[str, Any]) -> dict[str, str] | None:
    """Adopt existing well-formed MSSQL SELECT queries."""
    cmd = (rule.get("audit_command") or "").strip()
    if not cmd:
        return None

    # Must start with SELECT or EXEC (not shell commands)
    if not re.match(r'^(?:SELECT|EXEC)\s+', cmd, re.IGNORECASE):
        return None
    # Skip if it has shell pipes
    if '|' in cmd and re.search(r'\|\s*(grep|awk|sed|wc|cut)', cmd):
        return None

    title = _title(rule)
    tl = title.lower()
    cmd_l = cmd.lower()

    # Infer expression
    if "count(*)" in cmd_l:
        expr = "==0"
    elif "is_disabled" in cmd_l:
        expr = "==1"
    elif "value_in_use" in cmd_l or "value" in cmd_l:
        if "disabled" in tl or "off" in tl:
            expr = "==0"
        elif "enabled" in tl or "on" in tl:
            expr = "==1"
        else:
            expr = "not_empty"
    elif "version" in tl:
        expr = "not_empty"
    else:
        expr = "not_empty"

    return _result(
        audit_command=cmd,
        expected_output_regex=expr,
        expected_output_description=f"MSSQL check: {title}",
    )


_MSSQL_TEMPLATES = [
    _try_mssql_sys_config,
    _try_mssql_server_principals,
    _try_mssql_database_settings,
    _try_mssql_audit,
    _try_mssql_version,
    _try_mssql_existing_sql,
]


# ═══════════════════════════════════════════════════════════════════
# Oracle Templates
# ═══════════════════════════════════════════════════════════════════

# Map Oracle parameter names from common CIS rule keywords
_ORACLE_PARAM_MAP: dict[str, tuple[str, str]] = {
    "audit_trail":                  ("audit_trail", "!=NONE"),
    "audit_sys_operations":         ("audit_sys_operations", "==TRUE"),
    "remote_login_passwordfile":    ("remote_login_passwordfile", "==NONE"),
    "remote_os_authent":            ("remote_os_authent", "==FALSE"),
    "remote_os_roles":              ("remote_os_roles", "==FALSE"),
    "os_roles":                     ("os_roles", "==FALSE"),
    "sec_case_sensitive_logon":     ("sec_case_sensitive_logon", "==TRUE"),
    "sec_max_failed_login_attempts": ("sec_max_failed_login_attempts", "<=10"),
    "sec_protocol_error_further_action": ("sec_protocol_error_further_action", "contains:DROP"),
    "sec_protocol_error_trace_action": ("sec_protocol_error_trace_action", "contains:LOG"),
    "sec_return_server_release_banner": ("sec_return_server_release_banner", "==FALSE"),
    "resource_limit":               ("resource_limit", "==TRUE"),
    "remote_listener":              ("remote_listener", "not_empty"),
    "sql92_security":               ("sql92_security", "==TRUE"),
    "o7_dictionary_accessibility":  ("o7_dictionary_accessibility", "==FALSE"),
    "global_names":                 ("global_names", "==TRUE"),
    "utl_file_dir":                 ("utl_file_dir", "not_empty"),
    "shadow_core_dump":             ("shadow_core_dump", "contains:PARTIAL"),
    "mle_prog_languages":           ("mle_prog_languages", "not_empty"),
    "allow_group_access_to_sga":    ("allow_group_access_to_sga", "==FALSE"),
}


def _try_oracle_parameter(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Oracle rules checking V$PARAMETER / V$SYSTEM_PARAMETER."""
    text = _text(rule).lower()
    title = _title(rule)

    quoted = _extract_quoted(title)
    if quoted:
        param_lower = quoted.lower().strip()
        if param_lower in _ORACLE_PARAM_MAP:
            param_name, expr = _ORACLE_PARAM_MAP[param_lower]
            return _result(
                audit_command=f"SELECT VALUE FROM V$PARAMETER WHERE UPPER(NAME) = '{param_name.upper()}';",
                expected_output_regex=expr,
                expected_output_description=f"Oracle parameter {param_name}",
            )

    # Scan text for parameter names
    for keyword, (param_name, expr) in _ORACLE_PARAM_MAP.items():
        if keyword in text:
            if keyword in _title_lower(rule) or f"'{keyword}'" in text:
                return _result(
                    audit_command=f"SELECT VALUE FROM V$PARAMETER WHERE UPPER(NAME) = '{param_name.upper()}';",
                    expected_output_regex=expr,
                    expected_output_description=f"Oracle parameter {param_name}",
                )

    return None


def _try_oracle_user_accounts(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Oracle rules about user accounts (DBA_USERS)."""
    title = _title_lower(rule)
    text = _text(rule).lower()

    # Default user accounts locked/expired
    if ("default" in title and "account" in title) or "sample schema" in title:
        if "locked" in title or "expired" in title:
            return _result(
                audit_command=(
                    "SELECT COUNT(*) FROM DBA_USERS WHERE USERNAME IN "
                    "('SCOTT','HR','OE','PM','IX','SH','BI','ADAMS','BLAKE','CLARK','JONES') "
                    "AND ACCOUNT_STATUS NOT LIKE '%LOCKED%';"
                ),
                expected_output_regex="==0",
                expected_output_description="All default/sample accounts should be locked",
            )

    # PUBLIC privileges revoked
    if "public" in title and ("revoke" in title or "privilege" in title or "grant" in title):
        return _result(
            audit_command=(
                "SELECT COUNT(*) FROM DBA_TAB_PRIVS WHERE GRANTEE = 'PUBLIC' "
                "AND TABLE_NAME IN ('UTL_FILE','UTL_HTTP','UTL_TCP','UTL_SMTP','UTL_MAIL',"
                "'DBMS_RANDOM','DBMS_LOB','DBMS_SQL','DBMS_SYS_SQL','DBMS_ADVISOR');"
            ),
            expected_output_regex="==0",
            expected_output_description="Sensitive packages should not be granted to PUBLIC",
        )

    # DBA role restrictions
    if "dba" in title and ("restrict" in title or "limit" in title or "granted" in title):
        return _result(
            audit_command="SELECT GRANTEE FROM DBA_ROLE_PRIVS WHERE GRANTED_ROLE = 'DBA' AND GRANTEE NOT IN ('SYS','SYSTEM');",
            expected_output_regex="not_empty",
            expected_output_description="Review who has the DBA role",
        )

    return None


def _try_oracle_audit_settings(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Oracle audit configuration rules."""
    title = _title_lower(rule)

    if "unified audit" in title or "unified auditing" in title:
        return _result(
            audit_command="SELECT VALUE FROM V$OPTION WHERE PARAMETER = 'Unified Auditing';",
            expected_output_regex="==TRUE",
            expected_output_description="Unified Auditing should be enabled",
        )

    if "audit_trail" in title:
        return _result(
            audit_command="SELECT VALUE FROM V$PARAMETER WHERE NAME = 'audit_trail';",
            expected_output_regex="!=NONE",
            expected_output_description="Audit trail should be enabled (not NONE)",
        )

    return None


def _try_oracle_password_profile(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Oracle password profile rules (DBA_PROFILES)."""
    title = _title_lower(rule)
    text = _text(rule).lower()

    if "password" not in text and "profile" not in text:
        return None

    profiles_params = {
        "password_life_time": ("<=180", "should be 180 days or less"),
        "password_reuse_max": (">=24", "should require 24+ unique passwords"),
        "password_reuse_time": (">=365", "should be 365 days or more"),
        "password_grace_time": ("<=7", "should be 7 days or less"),
        "password_lock_time": (">=1", "should lock for at least 1 day"),
        "failed_login_attempts": ("<=5", "should lock after 5 or fewer failed attempts"),
        "password_verify_function": ("not_empty", "should have a verify function"),
        "password_rollover_time": ("==0", "should be 0"),
        "inactive_account_time": ("<=120", "should be 120 or less"),
    }

    for param, (expr, desc) in profiles_params.items():
        if param.replace("_", " ") in text or param.replace("_", "") in text.replace("_", ""):
            return _result(
                audit_command=(
                    f"SELECT PROFILE, RESOURCE_NAME, LIMIT FROM DBA_PROFILES "
                    f"WHERE RESOURCE_NAME = '{param.upper()}' AND PROFILE = 'DEFAULT';"
                ),
                expected_output_regex=expr,
                expected_output_description=f"Oracle password profile: {param} {desc}",
            )

    return None


def _try_oracle_config_file(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Oracle rules checking listener.ora / sqlnet.ora config files."""
    cmd = (rule.get("audit_command") or "").strip()
    title = _title(rule)
    tl = title.lower()

    # Detect grep patterns on listener.ora or sqlnet.ora
    for config_file in ("listener.ora", "sqlnet.ora"):
        if config_file in cmd.lower():
            # This rule already has a grep command against the right file
            expr = _oracle_infer_config_expression(tl)
            return _result(
                audit_command=cmd,
                expected_output_regex=expr,
                expected_output_description=f"Oracle {config_file} setting: {title}",
                command_transport="shell",
            )

    return None


def _oracle_infer_config_expression(title: str) -> str:
    """Infer expression from Oracle config-file rule title."""
    if "is not present" in title or "is not set" in title:
        return "==0"
    if "'required'" in title.lower():
        return "contains:REQUIRED"
    if "'12a'" in title.lower() or "12a" in title:
        return "contains:12a"
    if "'aes256'" in title.lower():
        return "contains:AES256"
    if "is set to" in title.lower():
        # Try to extract the expected value
        m = re.search(r"is set to\s+'([^']+)'", title, re.IGNORECASE)
        if m:
            return f"contains:{m.group(1)}"
    if "not" in title.lower() and "set" in title.lower():
        return "==0"
    return "not_empty"


def _try_oracle_count_query(rule: dict[str, Any]) -> dict[str, str] | None:
    """Adopt existing Oracle SELECT COUNT(*) or similar SQL queries."""
    cmd = (rule.get("audit_command") or "").strip()
    if not cmd:
        return None

    # Match well-formed SELECT queries (not shell commands)
    if re.match(r'^SELECT\s+', cmd, re.IGNORECASE) and not cmd.startswith(("su ", "sudo ", "ssh ")):
        # Skip if it has shell pipes (broken SQL)
        if '|' in cmd and re.search(r'\|\s*(grep|awk|sed|wc|cut)', cmd):
            return None
        title = _title(rule)
        # Infer expression from the query and title
        expr = _oracle_infer_sql_expression(cmd, title)
        return _result(
            audit_command=cmd,
            expected_output_regex=expr,
            expected_output_description=f"Oracle SQL check: {title}",
        )

    return None


def _oracle_infer_sql_expression(cmd: str, title: str) -> str:
    """Infer expression from Oracle SQL query shape and rule title."""
    tl = title.lower()
    cmd_l = cmd.lower()

    # COUNT(*) queries typically expect 0 (no violations)
    if "count(*)" in cmd_l:
        if "default password" in tl or "all default" in tl:
            return "==0"
        if "not" in tl and ("exist" in tl or "present" in tl):
            return "==0"
        if "custom" in tl:
            return "==0"
        # Conservative default for count queries: expect 0 violations
        return "==0"

    # Version/info queries
    if "version" in tl or "patch" in tl:
        return "not_empty"

    return "not_empty"


_ORACLE_TEMPLATES = [
    _try_oracle_parameter,
    _try_oracle_user_accounts,
    _try_oracle_audit_settings,
    _try_oracle_password_profile,
    _try_oracle_config_file,
    _try_oracle_count_query,
]


# ═══════════════════════════════════════════════════════════════════
# MySQL Templates
# ═══════════════════════════════════════════════════════════════════

_MYSQL_SHOW_MAP: dict[str, tuple[str, str]] = {
    "have_ssl":              ("have_ssl", "==YES"),
    "have_openssl":          ("have_openssl", "==YES"),
    "log_bin":               ("log_bin", "==ON"),
    "log_error":             ("log_error", "not_empty"),
    "log_error_verbosity":   ("log_error_verbosity", ">=2"),
    "log_raw":               ("log_raw", "==OFF"),
    "general_log":           ("general_log", "==OFF"),
    "slow_query_log":        ("slow_query_log", "==ON"),
    "audit_log":             ("audit_log_policy", "==ALL"),
    "local_infile":          ("local_infile", "==OFF"),
    "skip_networking":       ("skip_networking", "==OFF"),
    "sql_mode":              ("sql_mode", "contains:STRICT_ALL_TABLES"),
    "default_authentication_plugin": ("default_authentication_plugin", "contains:sha2"),
    "password_history":      ("password_history", ">=5"),
    "password_reuse_interval": ("password_reuse_interval", ">=365"),
    "disconnect_on_expired_password": ("disconnect_on_expired_password", "==ON"),
    "require_secure_transport": ("require_secure_transport", "==ON"),
    "max_connections":       ("max_connections", "not_empty"),
    "max_user_connections":  ("max_user_connections", "not_empty"),
    "log_bin_trust_function_creators": ("log_bin_trust_function_creators", "==OFF"),
    "binlog_encryption":     ("binlog_encryption", "==ON"),
    "table_encryption_privilege_check": ("table_encryption_privilege_check", "==ON"),
    "tls_version":           ("tls_version", "not_contains:TLSv1,TLSv1.1"),
    "admin_tls_version":     ("admin_tls_version", "not_contains:TLSv1,TLSv1.1"),
    "innodb_redo_log_encrypt": ("innodb_redo_log_encrypt", "==ON"),
    "innodb_undo_log_encrypt": ("innodb_undo_log_encrypt", "==ON"),
    "datadir":               ("datadir", "not_empty"),
}


def _try_mysql_show_variable(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MySQL rules using SHOW VARIABLES."""
    title = _title(rule)
    text = _text(rule).lower()

    quoted = _extract_quoted(title)
    if quoted:
        var_name = quoted.lower().strip()
        if var_name in _MYSQL_SHOW_MAP:
            real_name, expr = _MYSQL_SHOW_MAP[var_name]
            return _result(
                audit_command=f"SHOW VARIABLES LIKE '{real_name}';",
                expected_output_regex=expr,
                expected_output_description=f"MySQL variable {real_name}",
            )

    # Scan text for known variable names
    for keyword, (real_name, expr) in _MYSQL_SHOW_MAP.items():
        if keyword in text:
            if keyword in _title_lower(rule) or f"'{keyword}'" in text:
                return _result(
                    audit_command=f"SHOW VARIABLES LIKE '{real_name}';",
                    expected_output_regex=expr,
                    expected_output_description=f"MySQL variable {real_name}",
                )

    return None


def _try_mysql_select_variable(rule: dict[str, Any]) -> dict[str, str] | None:
    """Adopt existing SELECT @@variable or performance_schema queries."""
    cmd = (rule.get("audit_command") or "").strip()
    title = _title(rule)

    # Pattern: SELECT @@variable_name
    m = re.match(r'^SELECT\s+@@(\w+)\s*;?\s*$', cmd, re.IGNORECASE)
    if m:
        var = m.group(1).lower()
        expr = _mysql_infer_expression(title, var)
        return _result(
            audit_command=f"SELECT @@{var};",
            expected_output_regex=expr,
            expected_output_description=f"MySQL variable @@{var}",
        )

    # Pattern: SELECT ... FROM performance_schema.global_variables WHERE VARIABLE_NAME = '...'
    m = re.search(
        r"performance_schema\.global_variables\s+WHERE\s+(?:VARIABLE_NAME|variable_name)\s*=\s*'(\w+)'",
        cmd, re.IGNORECASE)
    if m:
        var = m.group(1).lower()
        expr = _mysql_infer_expression(title, var)
        return _result(
            audit_command=f"SELECT VARIABLE_VALUE FROM performance_schema.global_variables WHERE VARIABLE_NAME='{var}';",
            expected_output_regex=expr,
            expected_output_description=f"MySQL variable {var}",
        )

    return None


def _mysql_infer_expression(title: str, var_name: str) -> str:
    """Infer expected expression from MySQL rule title and variable name."""
    tl = title.lower()
    if "enabled" in tl or "is set to 'on'" in tl or "is on" in tl:
        return "==ON"
    if "disabled" in tl or "is set to 'off'" in tl or "is off" in tl:
        return "==OFF"
    if "'required'" in tl:
        return "contains:REQUIRED"
    if "'aes256'" in tl or "aes256" in tl:
        return "contains:AES256"
    if "tls" in tl and "version" in tl:
        return "not_contains:TLSv1,"
    return "not_empty"


def _try_mysql_user_security(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MySQL user account and privilege rules."""
    title = _title_lower(rule)

    # Anonymous accounts
    if "anonymous" in title and ("account" in title or "user" in title):
        return _result(
            audit_command="SELECT COUNT(*) FROM mysql.user WHERE user = '';",
            expected_output_regex="==0",
            expected_output_description="No anonymous user accounts should exist",
        )

    # Wildcard hosts
    if ("wildcard" in title or "'%'" in title) and "host" in title:
        return _result(
            audit_command="SELECT user, host FROM mysql.user WHERE host = '%';",
            expected_output_regex="not_empty",
            expected_output_description="Review accounts with wildcard host access",
        )

    # Password expiration
    if "password" in title and "expir" in title:
        return _result(
            audit_command="SELECT COUNT(*) FROM mysql.user WHERE password_expired = 'N' AND password_lifetime IS NULL AND user NOT IN ('mysql.sys','mysql.session','mysql.infoschema');",
            expected_output_regex="==0",
            expected_output_description="All user accounts should have password expiration configured",
        )

    # SUPER privilege
    if "super" in title and "privilege" in title:
        return _result(
            audit_command="SELECT user, host FROM mysql.user WHERE Super_priv = 'Y' AND user NOT IN ('root','mysql.sys');",
            expected_output_regex="not_empty",
            expected_output_description="Review accounts with SUPER privilege",
        )

    # FILE privilege
    if "file" in title and "privilege" in title:
        return _result(
            audit_command="SELECT user, host FROM mysql.user WHERE File_priv = 'Y';",
            expected_output_regex="not_empty",
            expected_output_description="Review accounts with FILE privilege",
        )

    # PROCESS privilege
    if "process" in title and "privilege" in title:
        return _result(
            audit_command="SELECT user, host FROM mysql.user WHERE Process_priv = 'Y';",
            expected_output_regex="not_empty",
            expected_output_description="Review accounts with PROCESS privilege",
        )

    return None


def _try_mysql_version(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MySQL version/update rules."""
    title = _title_lower(rule)
    if "latest" in title and ("update" in title or "patch" in title or "version" in title):
        return _result(
            audit_command="SELECT VERSION();",
            expected_output_regex="not_empty",
            expected_output_description="MySQL version should be current",
        )
    return None


def _try_mysql_existing_sql(rule: dict[str, Any]) -> dict[str, str] | None:
    """Adopt existing well-formed MySQL SELECT/SHOW queries."""
    cmd = (rule.get("audit_command") or "").strip()
    if not cmd:
        return None

    # Must start with SELECT or SHOW (not shell commands)
    if not re.match(r'^(?:SELECT|SHOW)\s+', cmd, re.IGNORECASE):
        return None
    # Skip if it has shell pipes (broken/hybrid command)
    if '|' in cmd and re.search(r'\|\s*(grep|awk|sed|wc|cut)', cmd):
        return None

    title = _title(rule)
    tl = title.lower()
    cmd_l = cmd.lower()

    # Infer expression
    if "count(*)" in cmd_l:
        # Most COUNT queries check for violations -> expect 0
        if "not granted" in tl or "is not" in tl or "limited" in tl:
            expr = "==0"
        else:
            expr = "not_empty"
    elif "show variables" in cmd_l or "show global variables" in cmd_l:
        expr = "not_empty"
    else:
        expr = "not_empty"

    return _result(
        audit_command=cmd,
        expected_output_regex=expr,
        expected_output_description=f"MySQL check: {title}",
    )


_MYSQL_TEMPLATES = [
    _try_mysql_show_variable,
    _try_mysql_select_variable,
    _try_mysql_user_security,
    _try_mysql_version,
    _try_mysql_existing_sql,
]


# ═══════════════════════════════════════════════════════════════════
# MongoDB Templates
# ═══════════════════════════════════════════════════════════════════

def _try_mongo_config(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MongoDB configuration file rules."""
    text = _text(rule).lower()
    title = _title_lower(rule)

    config_checks = {
        "authorization": ("authorization", "contains:enabled"),
        "authentication": ("security.authorization", "contains:enabled"),
        "audit": ("auditLog.destination", "not_empty"),
        "tls": ("net.tls.mode", "contains:requireTLS"),
        "ssl": ("net.ssl.mode", "contains:requireSSL"),
        "bind_ip": ("net.bindIp", "not_empty"),
        "bindip": ("net.bindIp", "not_empty"),
        "port": ("net.port", "not_empty"),
        "keyfile": ("security.keyFile", "not_empty"),
        "logpath": ("systemLog.path", "not_empty"),
        "logappend": ("systemLog.logAppend", "contains:true"),
        "quiet": ("systemLog.quiet", "not_contains:true"),
        "noscripting": ("security.javascriptEnabled", "contains:false"),
        "javascript": ("security.javascriptEnabled", "contains:false"),
    }

    for keyword, (config_key, expr) in config_checks.items():
        if keyword in title or keyword in text[:200]:
            return _result(
                audit_command=f"grep -i '{config_key.split('.')[-1]}' /etc/mongod.conf",
                expected_output_regex=expr,
                expected_output_description=f"MongoDB config: {config_key}",
                command_transport="shell",
            )

    return None


def _try_mongo_version(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MongoDB version rules."""
    title = _title_lower(rule)
    if "latest" in title or "version" in title or "patch" in title:
        if "install" in title or "update" in title or "applied" in title:
            return _result(
                audit_command="mongod --version | head -1",
                expected_output_regex="not_empty",
                expected_output_description="MongoDB version should be current",
                command_transport="shell",
            )
    return None


def _try_mongo_user_admin(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match MongoDB user/role rules."""
    title = _title_lower(rule)

    if "superuser" in title or "root" in title or "admin" in title:
        if "restrict" in title or "limit" in title or "ensure" in title:
            return _result(
                audit_command="db.getUsers({filter: {roles: {$elemMatch: {role: 'root'}}}})",
                expected_output_regex="not_empty",
                expected_output_description="Review accounts with root/admin role",
                command_transport="shell",
            )

    return None


_MONGODB_TEMPLATES = [
    _try_mongo_config,
    _try_mongo_version,
    _try_mongo_user_admin,
]


# ═══════════════════════════════════════════════════════════════════
# Network Device Templates (expansion)
# ═══════════════════════════════════════════════════════════════════

def _try_fortigate_command(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match FortiGate CLI rules."""
    text = _text(rule).lower()
    title = _title_lower(rule)

    # System settings
    if "password policy" in title or "admin password" in title:
        return _result(
            audit_command="get system password-policy",
            expected_output_regex="not_empty",
            expected_output_description="FortiGate password policy settings",
            command_transport="cli",
        )

    if "admin timeout" in title or "idle timeout" in title:
        return _result(
            audit_command="get system global | grep admintimeout",
            expected_output_regex="not_empty",
            expected_output_description="Admin session timeout setting",
            command_transport="cli",
        )

    if "ntp" in title:
        return _result(
            audit_command="get system ntp",
            expected_output_regex="contains:enable",
            expected_output_description="NTP should be enabled",
            command_transport="cli",
        )

    if "dns" in title and "server" in title:
        return _result(
            audit_command="get system dns",
            expected_output_regex="not_empty",
            expected_output_description="DNS servers should be configured",
            command_transport="cli",
        )

    if "firmware" in title or "version" in title:
        if "latest" in title or "update" in title:
            return _result(
                audit_command="get system status | grep Version",
                expected_output_regex="not_empty",
                expected_output_description="FortiGate firmware version",
                command_transport="cli",
            )

    return None


def _try_paloalto_command(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Palo Alto CLI rules."""
    text = _text(rule).lower()
    title = _title_lower(rule)

    if "idle timeout" in title or "session timeout" in title:
        return _result(
            audit_command="show deviceconfig system | match timeout",
            expected_output_regex="not_empty",
            expected_output_description="Session timeout setting",
            command_transport="cli",
        )

    if "password complexity" in title or "password profile" in title:
        return _result(
            audit_command="show deviceconfig system | match password-complexity",
            expected_output_regex="contains:yes",
            expected_output_description="Password complexity should be enabled",
            command_transport="cli",
        )

    if "ntp" in title:
        return _result(
            audit_command="show ntp",
            expected_output_regex="not_empty",
            expected_output_description="NTP should be configured",
            command_transport="cli",
        )

    if "software" in title or "version" in title:
        if "latest" in title or "update" in title:
            return _result(
                audit_command="show system info | match sw-version",
                expected_output_regex="not_empty",
                expected_output_description="PAN-OS software version",
                command_transport="cli",
            )

    return None


_NETWORK_EXT_TEMPLATES = [
    _try_fortigate_command,
    _try_paloalto_command,
]


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

_DB_TEMPLATES_BY_PLATFORM: dict[str, list] = {
    # PostgreSQL
    "postgresql_16": _PG_TEMPLATES,
    "postgresql_17": _PG_TEMPLATES,
    "postgresql": _PG_TEMPLATES,
    # Oracle
    "oracle_database_23ai": _ORACLE_TEMPLATES,
    "oracle": _ORACLE_TEMPLATES,
    # MSSQL
    "microsoft_sql_server_2019": _MSSQL_TEMPLATES,
    "microsoft_sql_server_2022": _MSSQL_TEMPLATES,
    "windows_sql_server_2017": _MSSQL_TEMPLATES,
    "windows_sql_server_2022": _MSSQL_TEMPLATES,
    "mssql": _MSSQL_TEMPLATES,
    # MySQL
    "mysql_enterprise_edition_84": _MYSQL_TEMPLATES,
    "mysql": _MYSQL_TEMPLATES,
    # MongoDB
    "mongodb_32": _MONGODB_TEMPLATES,
    "mongodb_8": _MONGODB_TEMPLATES,
    "mongodb": _MONGODB_TEMPLATES,
    # Network (expanded)
    "network_fortigate_74x": _NETWORK_EXT_TEMPLATES,
    "fortigate": _NETWORK_EXT_TEMPLATES,
    "palo_alto_firewall_10": _NETWORK_EXT_TEMPLATES,
    "palo_alto_firewall_11": _NETWORK_EXT_TEMPLATES,
    "paloalto": _NETWORK_EXT_TEMPLATES,
}


def match_db_template(
    rule: dict[str, Any],
    platform: str,
) -> dict[str, str] | None:
    """Try to match *rule* to a database/network-device template.

    Returns a dict with keys ``audit_command``, ``expected_output_regex``,
    ``expected_output_description``, ``command_transport`` — or ``None``
    when no template matches and the rule should fall through to the LLM.
    """
    # Normalize platform name
    platform_lower = (platform or "").lower().replace("-", "_").replace(" ", "_")

    # Try exact platform match first
    templates = _DB_TEMPLATES_BY_PLATFORM.get(platform_lower)

    # Fallback: try prefix matching
    if templates is None:
        for key, tmpl_list in _DB_TEMPLATES_BY_PLATFORM.items():
            if platform_lower.startswith(key) or key.startswith(platform_lower):
                templates = tmpl_list
                break

    if templates is None:
        return None

    for fn in templates:
        result = fn(rule)
        if result:
            return result

    return None
