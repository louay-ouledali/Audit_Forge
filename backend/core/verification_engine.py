"""Verification engine: syntax and safety checks for generated audit commands."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.core.platform_family import normalize_platform_family
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.verification_report import VerificationReport

logger = logging.getLogger("auditforge.verify")

# ---------------------------------------------------------------------------
# Dangerous command patterns by platform family
# ---------------------------------------------------------------------------
# IMPORTANT design principle: audit commands are READ-ONLY by nature.
# Patterns must avoid false-positives on legitimate read-only constructs such as
#   - grep/awk/find pipelines that mention modify-keywords inside search strings
#   - "show running-config" (network) which contains "config" in a safe context
#   - SQL SELECT queries that reference DML keywords as column/string values
#   - "dnf check-update" vs "dnf update" on Linux
# ---------------------------------------------------------------------------

DANGEROUS_LINUX = [
    (r'\brm\s+-', "rm with flags - deletes files"),
    (r'\brm\s+/', "rm on absolute path - deletes files"),
    (r'\bmkdir\b', "mkdir - creates directories"),
    (r'\btouch\b', "touch - creates/modifies files"),
    # chmod/chown/chgrp as actual commands (not inside stat/find -printf output)
    (r'(?:^|[;&|]\s*)chmod\b', "chmod - changes permissions"),
    (r'(?:^|[;&|]\s*)chown\b', "chown - changes ownership"),
    (r'(?:^|[;&|]\s*)chgrp\b', "chgrp - changes group"),
    (r'\bsed\s+-i\b', "sed -i - in-place file edit"),
    # tee writing to a real file (not /dev/null)
    (r'\btee\s+(?!/dev/null)', "tee - writes to file"),
    # Redirect to absolute path - but NOT 2>/dev/null or >/dev/null (harmless)
    (r'>\s*/(?!dev/null)', "redirect to absolute path - writes to file"),
    # Append redirect - but NOT 2>>/dev/null
    (r'(?<!\d)>>\s*/(?!dev/null)', "append redirect - writes to file"),
    (r'\bsystemctl\s+(start|stop|restart|enable|disable|mask|unmask)\b', "systemctl modification"),
    (r'\bservice\s+\S+\s+(start|stop|restart)\b', "service modification"),
    (r'\bapt\b.*\b(install|remove|purge|autoremove)\b', "apt package modification"),
    (r'\bapt-get\b.*\b(install|remove|purge)\b', "apt-get package modification"),
    (r'\byum\s+(install|remove|erase|update)\b', "yum package modification"),
    # dnf: "dnf update" is dangerous, "dnf check-update" is safe
    (r'\bdnf\s+(install|remove|erase|update)\b', "dnf package modification"),
    (r'\buseradd\s+(?!-D\b)', "useradd - creates user"),
    (r"(?<!['\"/])\buserdel\b", "userdel - deletes user"),
    (r"(?<!['\"/])\busermod\b", "usermod - modifies user"),
    # passwd as a COMMAND (not /etc/passwd file path or passwd- backup file)
    (r'(?<!/)\bpasswd\s+(?!-S\b)(?!-)', "passwd - changes password"),
    (r'\biptables\s+-[ADIFX]\b', "iptables modification"),
    (r'\bufw\s+(allow|deny|enable|disable|delete)\b', "ufw modification"),
    (r'\bdd\s+', "dd - raw disk write potentially"),
    (r'\bmkfs\b', "mkfs - formats filesystem"),
    (r'\breboot\b', "reboot - restarts system"),
    # shutdown as a standalone command, not inside awk/grep regex patterns
    (r'(?:^|[;&])\s*shutdown\b', "shutdown - shuts down system"),
    (r'\bpoweroff\b', "poweroff - shuts down system"),
    (r'\bkill\s+-', "kill with signal - terminates process"),
    (r'\bkillall\b', "killall - terminates processes"),
    (r'\bsysctl\s+-w\b', "sysctl -w - modifies kernel parameter"),
]

DANGEROUS_WINDOWS = [
    (r'Set-ItemProperty', "Set-ItemProperty - modifies registry"),
    (r'New-ItemProperty', "New-ItemProperty - creates registry value"),
    (r'Remove-ItemProperty', "Remove-ItemProperty - deletes registry value"),
    (r'Remove-Item', "Remove-Item - deletes files/registry"),
    (r'New-Item', "New-Item - creates files/directories/registry"),
    (r'Set-Content', "Set-Content - writes to file"),
    (r'Add-Content', "Add-Content - appends to file"),
    (r'Stop-Service', "Stops a service"),
    (r'Start-Service', "Starts a service"),
    (r'Restart-Service', "Restarts a service"),
    (r'Set-Service', "Modifies service configuration"),
    (r'Set-ExecutionPolicy', "Changes execution policy"),
    (r'New-LocalUser', "Creates local user"),
    (r'Remove-LocalUser', "Deletes local user"),
    (r'Restart-Computer', "Restarts computer"),
    (r'Stop-Computer', "Shuts down computer"),
    (r'Stop-Process', "Terminates process"),
    (r'Clear-EventLog', "Clears event log"),
]

# SQL patterns: only flag DML/DDL at statement-start position.
# SELECT/SHOW queries that *reference* these keywords as values are safe.
DANGEROUS_SQL = [
    (r'(?:^|;\s*)DROP\b', "DROP - destroys database objects"),
    (r'(?:^|;\s*)ALTER\b', "ALTER - modifies database objects"),
    (r'(?:^|;\s*)CREATE\b', "CREATE - creates database objects"),
    (r'(?:^|;\s*)INSERT\b', "INSERT - adds data"),
    (r'(?:^|;\s*)UPDATE\b', "UPDATE - modifies data"),
    (r'(?:^|;\s*)DELETE\b', "DELETE - removes data"),
    (r'(?:^|;\s*)TRUNCATE\b', "TRUNCATE - removes all data"),
    (r'(?:^|;\s*)GRANT\b', "GRANT - modifies permissions"),
    (r'(?:^|;\s*)REVOKE\b', "REVOKE - modifies permissions"),
    (r'(?:^|;\s*)SHUTDOWN\b', "SHUTDOWN - shuts down database"),
]

# Network patterns: only match dangerous keywords at *command-start* position.
# "show running-config | include ..." and similar read-only constructs are safe.
# The prefix (?:^|[;&]\s*) ensures the keyword is the first word of a command
# (after start of string, semicolon, or ampersand) — never after a pipe or
# inside a quoted search string.
DANGEROUS_NETWORK = [
    (r'(?:^|[;&]\s*)configure\s+terminal\b', "Enters configuration mode"),
    (r'(?:^|[;&]\s*)conf\s+t\b', "Enters configuration mode (shorthand)"),
    (r'(?:^|[;&]\s*)no\s+', "no - negates/removes configuration"),
    (r'(?:^|[;&]\s*)write\s+memory\b', "Writes configuration to flash"),
    (r'(?:^|[;&]\s*)reload\b', "Reloads device"),
    (r'(?:^|[;&]\s*)shutdown\b', "Shuts down interface"),
    (r'(?:^|[;&]\s*)set\s', "set - adds configuration"),
    (r'(?:^|[;&]\s*)delete\s', "delete - removes configuration"),
    (r'(?:^|[;&]\s*)commit\b', "commit - applies configuration changes"),
    # "config" at command start — does NOT match "show running-config ..."
    (r'(?:^|[;&]\s*)config(?:ure)?\s', "config - enters configuration mode"),
    (r'(?:^|[;&]\s*)unset\s', "unset - removes configuration"),
]

PLATFORM_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "linux": DANGEROUS_LINUX,
    "windows": DANGEROUS_WINDOWS,
    "database": DANGEROUS_SQL,
    "network": DANGEROUS_NETWORK,
}


def _is_readonly_network_cmd(cmd: str) -> bool:
    """Return True if the network command is clearly read-only (show/display/get).

    Network devices use ``show``, ``display`` (Huawei), ``get`` (FortiGate /
    Juniper), ``diagnose`` (FortiGate) as read-only prefixes.  When the first
    word is one of these the entire pipeline is safe regardless of what keywords
    appear later in the output filter.
    """
    return bool(re.match(
        r'\s*(show|display|get|diagnose|run\s+show|more)\b',
        cmd,
        re.IGNORECASE,
    ))


def _is_readonly_sql_cmd(cmd: str) -> bool:
    """Return True if a database command is a read-only SQL query.

    Checks for the presence of SELECT / SHOW / EXPLAIN / WITH as the primary
    SQL statement.  If the command invokes a DB client (``psql``, ``mysql``,
    ``sqlcmd``, ``sqlplus``, ``Invoke-Sqlcmd``) and the SQL portion starts with
    a read-only keyword, any DML/DDL keywords appearing further in the string
    are just referenced values — not dangerous.
    """
    first_keyword = cmd.strip().split()[0].upper() if cmd.strip() else ""
    return first_keyword in ("SELECT", "SHOW", "EXPLAIN", "WITH")

# Patterns that indicate a command still contains unresolved placeholders
# NOTE: \{...\} is excluded because auditpol GUIDs like {0cce923f-69ae-11d9-bed3-505054503030} are real.
# Instead we match only obvious placeholders e.g. {PLACEHOLDER}, {your_value}, {VALUE_HERE}
PLACEHOLDER_PATTERNS = [
    # {PLACEHOLDER} but NOT ${Status} (shell variable), NOT %{SESSIONID} (Tomcat
    # log format), and NOT awk keywords like {print}
    r'(?<!\$)(?<!%)\{(?!print|else|next|exit|true|false|null|done|gsub|split|match|sub)[A-Za-z_]{3,}\}',
    r'(?<!\$)(?<!%)\{your_\w+\}',  # {your_value} but NOT ${your_value}
    # <PLACEHOLDER> with ALL-UPPERCASE names only — avoids false-positives on
    # XML tags like <interface>, <address> in Juniper/network display output
    r'<[A-Z][A-Z_0-9]{2,}>',       # <PLACEHOLDER>, <VALUE_HERE>, <YOUR_HOST>
    r'<your_\w+>',                  # <your_value>
    r'\[REPLACE\]',
    r'\bTODO\b',
    r'\bFIXME\b',
]


def _check_syntax(audit_command: str | None) -> dict:
    """Level 1: Syntax check. Returns {result: str, message: str}."""
    if not audit_command or not audit_command.strip():
        return {"result": "fail", "message": "Audit command is empty"}

    stripped = audit_command.strip()
    if len(stripped) < 3:
        return {"result": "fail", "message": "Command is too short to be valid"}

    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, stripped):
            return {"result": "fail", "message": f"Command contains placeholder: {pattern}"}

    # Check for known-unbound environment variables
    _KNOWN_UNBOUND = {
        "CATALINA_HOME", "CATALINA_BASE", "APACHE_PREFIX", "HTTPD_ROOT",
        "BIND_HOME", "BIND_DIR", "NAMED_DIR", "FWDIR", "CPDIR",
        "RUNDIR", "DYNDIR", "SLAVEDIR", "DATADIR", "LOGDIR", "DOCROOT",
    }
    for m in re.finditer(r'\$\{?([A-Z][A-Z_0-9]{2,})\}?', stripped):
        var = m.group(1)
        if var in _KNOWN_UNBOUND:
            # Check if the variable is defined earlier in the same command
            if not re.search(rf'\b{re.escape(var)}=', stripped[:m.start()]):
                return {"result": "fail", "message": f"Unbound environment variable: ${var}"}

    return {"result": "pass", "message": "Syntax OK"}


def _check_safety(audit_command: str | None, platform_family: str) -> dict:
    """Level 2: Safety check. Returns {result: str, message: str, details: list}.

    Context-aware: skips pattern checks for commands that are clearly read-only
    (e.g. ``show running-config`` on network, ``SELECT`` queries on databases).
    """
    if not audit_command or not audit_command.strip():
        return {"result": "fail", "message": "No command to check", "details": []}

    stripped = audit_command.strip()

    # Normalize platform_family
    pf = normalize_platform_family(platform_family)

    # ── Context-aware bypass ──────────────────────────────────────────────
    # Network read-only commands (show, display, get, diagnose …) are safe
    if pf == "network" and _is_readonly_network_cmd(stripped):
        return {"result": "pass", "message": "Read-only network command", "details": []}

    # SQL read-only queries (SELECT, SHOW, EXPLAIN, WITH) are safe even when
    # they reference DML/DDL keywords as column values or string literals
    if pf == "database" and _is_readonly_sql_cmd(stripped):
        return {"result": "pass", "message": "Read-only SQL query", "details": []}

    # ── Standard pattern matching ─────────────────────────────────────────
    patterns = PLATFORM_PATTERNS.get(pf, DANGEROUS_LINUX)
    hits: list[str] = []
    for pattern, description in patterns:
        if re.search(pattern, stripped, re.IGNORECASE):
            hits.append(description)

    if hits:
        return {
            "result": "fail",
            "message": f"Dangerous patterns detected: {len(hits)} issue(s)",
            "details": hits,
        }
    return {"result": "pass", "message": "No dangerous patterns detected", "details": []}


def _check_cross_reference(audit_command: str | None, previous_commands: str | None) -> dict:
    """Level 3: Cross-reference check. Compare with previously verified versions."""
    if not previous_commands:
        return {"result": "skip", "message": "No previous commands to compare"}

    if not audit_command:
        return {"result": "warn", "message": "Current command is empty but previous versions exist"}

    try:
        history = json.loads(previous_commands) if isinstance(previous_commands, str) else previous_commands
    except (json.JSONDecodeError, TypeError):
        return {"result": "skip", "message": "Cannot parse previous command history"}

    if not isinstance(history, list) or len(history) == 0:
        return {"result": "skip", "message": "No previous commands to compare"}

    last_cmd = history[-1].get("audit_command", "") if isinstance(history[-1], dict) else str(history[-1])
    if not last_cmd:
        return {"result": "skip", "message": "Previous command is empty"}
    if (audit_command or "").strip() == last_cmd.strip():
        return {"result": "pass", "message": "Command identical to last verified version"}

    return {"result": "warn", "message": "Command differs from previous version"}


def verify_single_command(audit_command: str | None, platform_family: str) -> dict:
    """Verify a single audit command. Returns {passed: bool, issues: [...]}."""
    issues: list[dict[str, str]] = []

    if not audit_command or not audit_command.strip():
        return {"passed": False, "issues": [{"type": "empty", "message": "Audit command is empty"}]}

    # Normalize platform_family
    pf = platform_family.lower() if platform_family else "linux"
    if pf in ("unix", "macos"):
        pf = "linux"

    # Syntax check: verify the command looks valid
    stripped = audit_command.strip()
    if len(stripped) < 3:
        issues.append({"type": "syntax", "message": "Command is too short to be valid"})

    # Check for common placeholder patterns
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, stripped):
            issues.append({"type": "syntax", "message": f"Command contains placeholder: {pattern}"})
            break

    # Safety check: verify command is read-only
    # Context-aware bypass for read-only commands
    skip_safety = False
    if pf == "network" and _is_readonly_network_cmd(stripped):
        skip_safety = True
    elif pf == "database" and _is_readonly_sql_cmd(stripped):
        skip_safety = True

    if not skip_safety:
        patterns = PLATFORM_PATTERNS.get(pf, DANGEROUS_LINUX)
        for pattern, description in patterns:
            if re.search(pattern, stripped, re.IGNORECASE):
                issues.append({"type": "safety", "message": f"Dangerous pattern: {description}"})

    return {"passed": len(issues) == 0, "issues": issues}


def verify_regex(regex_str: str | None) -> dict:
    """Verify that an expected-output expression is valid.

    Accepts both new comparison expressions (>=24, ==1, contains:text)
    and legacy regex patterns. Returns ``{"valid": False}`` when
    *regex_str* is empty or ``None``.
    """
    from backend.core.comparison_engine import validate_expression

    if not regex_str or not regex_str.strip():
        return {"valid": False, "error": "Expression is empty"}

    error = validate_expression(regex_str)
    if error:
        return {"valid": False, "error": error}

    return {"valid": True, "error": None}


# Patterns that indicate the regex is an English phrase, not a real pattern
_ENGLISH_REGEX_PATTERNS = [
    (re.compile(r"^\d+\s+or\s+more", re.I), "Regex looks like English text, not a pattern"),
    (re.compile(r"^\d+\s+or\s+fewer", re.I), "Regex looks like English text, not a pattern"),
    (re.compile(r"^\d+\s+or\s+greater", re.I), "Regex looks like English text, not a pattern"),
    (re.compile(r"^\d+\s+or\s+less", re.I), "Regex looks like English text, not a pattern"),
    (re.compile(r"enabled\s+or\s+greater", re.I), "Regex looks like English text, not a pattern"),
    (re.compile(r"characters?\s*$", re.I), "Regex ends with prose ('characters')"),
    (re.compile(r"passwords?\s*$", re.I), "Regex ends with prose ('passwords')"),
    (re.compile(r"minutes?\s*$", re.I), "Regex ends with prose ('minutes')"),
    (re.compile(r"days?\s*$", re.I), "Regex ends with prose ('days')"),
    (re.compile(r"^(?:should|must|needs?\s+to|is\s+set\s+to)\b", re.I), "Regex is an English sentence"),
    (re.compile(r"^(?:the\s+|this\s+|a\s+)", re.I), "Regex starts with an article (English prose)"),
    (re.compile(r"\bshould\s+be\b", re.I), "Regex contains 'should be' (English prose)"),
    (re.compile(r"\bmust\s+be\b", re.I), "Regex contains 'must be' (English prose)"),
    (re.compile(r"\bor\s+higher\b", re.I), "Regex contains 'or higher' (English prose)"),
    (re.compile(r"\bor\s+lower\b", re.I), "Regex contains 'or lower' (English prose)"),
    (re.compile(r"\bor\s+above\b", re.I), "Regex contains 'or above' (English prose)"),
    (re.compile(r"\bor\s+below\b", re.I), "Regex contains 'or below' (English prose)"),
    (re.compile(r"^(?:PASS|FAIL|Compliant|Non-compliant|Yes|No)\s*$", re.I), "Regex is a compliance verdict, not command output"),
    (re.compile(r"\bat\s+least\s+\d+", re.I), "Regex contains 'at least N' (English prose)"),
    (re.compile(r"\bno\s+more\s+than\b", re.I), "Regex contains 'no more than' (English prose)"),
    (re.compile(r"\bgreater\s+than\b", re.I), "Regex contains 'greater than' (English prose)"),
    (re.compile(r"\bless\s+than\b", re.I), "Regex contains 'less than' (English prose)"),
]


def _check_regex_quality(regex_str: str) -> str | None:
    """Return an error message if the regex is a bad English-phrase pattern."""
    stripped = regex_str.strip()
    for pattern, message in _ENGLISH_REGEX_PATTERNS:
        if pattern.search(stripped):
            return f"{message}: '{stripped}'"
    return None


def _check_semantic_quality(audit_command: str | None, expected_regex: str | None,
                            command_transport: str | None, platform_family: str) -> dict:
    """Level 4: Semantic quality check. Catches higher-level quality issues.

    Returns {result: str, message: str, details: list[str]}.
    """
    details: list[str] = []

    if not audit_command:
        return {"result": "skip", "message": "No command to check", "details": []}

    cmd = audit_command.strip()
    transport = (command_transport or "").lower()

    # 1. Transport-content mismatch: SQL commands with shell pipes
    if transport == "sql":
        shell_pipe_re = re.compile(r"\|\s*(?:grep|awk|sed|wc|cut|sort|head|tail|tr|uniq)\b")
        if shell_pipe_re.search(cmd):
            m = shell_pipe_re.search(cmd)
            details.append(f"SQL transport has shell pipe '{m.group(0).strip()}' — DB connector will error")

    # 2. CLI transport with shell builtins
    if transport == "cli":
        for builtin in ("echo ", "cat ", "grep ", "awk ", "printf "):
            if cmd.lower().startswith(builtin):
                details.append(f"CLI transport starts with shell builtin '{builtin.strip()}'")
                break

    # 3. Tautological expressions
    if expected_regex:
        expr = expected_regex.strip()
        if expr == ">=0":
            details.append("Tautological expression: >=0 always passes for non-negative output")
        if expr.startswith("contains:") and not expr[len("contains:"):].strip():
            details.append("Empty contains: value — matches any non-empty output")

    # 4. Stub on scored: echo/Write-Output with manual-check content
    cmd_lower = cmd.lower()
    stub_prefixes = ("echo ", "write-output ", "write-host ")
    manual_keywords = ("manual", "not-auditable", "not auditable", "physical inspection",
                       "requires manual", "cannot be automated")
    for prefix in stub_prefixes:
        if cmd_lower.startswith(prefix):
            for kw in manual_keywords:
                if kw in cmd_lower:
                    details.append(f"Stub command '{prefix.strip()} ...{kw}...' — always passes")
                    break
            break

    if details:
        return {
            "result": "warn",
            "message": f"Semantic quality issues: {len(details)} found",
            "details": details,
        }
    return {"result": "pass", "message": "Semantic quality OK", "details": []}


def verify_command_full(cmd: RuleCommand, platform_family: str, db: Session) -> dict:
    """Run full three-tier verification on a single command and create reports.

    Returns {passed: bool, syntax: dict, safety: dict, cross_reference: dict, regex: dict}.
    """
    now = datetime.now(timezone.utc)

    # Delete old reports for this command
    db.query(VerificationReport).filter(
        VerificationReport.rule_command_id == cmd.id
    ).delete()

    # Level 1: Syntax
    syntax = _check_syntax(cmd.audit_command)
    db.add(VerificationReport(
        rule_command_id=cmd.id,
        level="syntax",
        result=syntax["result"],
        message=syntax["message"],
        auto_fixable=syntax["result"] == "fail",
        run_at=now,
    ))

    # Level 2: Safety
    safety = _check_safety(cmd.audit_command, platform_family)
    db.add(VerificationReport(
        rule_command_id=cmd.id,
        level="safety",
        result=safety["result"],
        message=safety["message"],
        details=json.dumps(safety.get("details", [])),
        auto_fixable=False,
        run_at=now,
    ))

    # Level 3: Cross-reference
    cross_ref = _check_cross_reference(cmd.audit_command, cmd.previous_commands)
    db.add(VerificationReport(
        rule_command_id=cmd.id,
        level="cross_reference",
        result=cross_ref["result"],
        message=cross_ref["message"],
        auto_fixable=False,
        run_at=now,
    ))

    # Level 4: Semantic quality
    semantic = _check_semantic_quality(
        cmd.audit_command, cmd.expected_output_regex,
        cmd.command_transport, platform_family,
    )
    db.add(VerificationReport(
        rule_command_id=cmd.id,
        level="semantic_quality",
        result=semantic["result"],
        message=semantic["message"],
        details=json.dumps(semantic.get("details", [])),
        auto_fixable=False,
        run_at=now,
    ))

    # Regex validation — empty regex is acceptable (not every rule needs one)
    regex_result = verify_regex(cmd.expected_output_regex)
    regex_is_empty = not cmd.expected_output_regex or not cmd.expected_output_regex.strip()
    regex_ok = regex_result["valid"] or regex_is_empty
    regex_check = {
        "result": "pass" if regex_ok else "fail",
        "message": "Valid regex" if regex_ok else f"Invalid regex: {regex_result['error']}",
    }
    db.add(VerificationReport(
        rule_command_id=cmd.id,
        level="regex",
        result=regex_check["result"],
        message=regex_check["message"],
        auto_fixable=regex_check["result"] == "fail",
        run_at=now,
    ))

    # Overall result
    has_failure = (
        syntax["result"] == "fail"
        or safety["result"] == "fail"
        or regex_check["result"] == "fail"
    )
    passed = not has_failure

    return {
        "passed": passed,
        "syntax": syntax,
        "safety": safety,
        "cross_reference": cross_ref,
        "semantic_quality": semantic,
        "regex": regex_check,
    }


async def run_verification(benchmark_id: int) -> None:
    """Run verification on all commands for a benchmark."""
    db = SessionLocal()
    try:
        benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
        if not benchmark:
            logger.error("Benchmark %d not found", benchmark_id)
            return

        benchmark.verification_status = "processing"
        db.commit()

        platform_family = benchmark.platform_family

        commands = (
            db.query(RuleCommand)
            .join(Rule)
            .filter(Rule.benchmark_id == benchmark_id)
            .all()
        )

        total = len(commands)
        passed = 0
        failed = 0

        # Check auto-protect setting
        from backend.models.app_settings import AppSettings
        auto_protect_row = db.query(AppSettings).filter(
            AppSettings.key == "verification_auto_protect_passing"
        ).first()
        auto_protect = auto_protect_row and auto_protect_row.value == "true"

        for cmd in commands:
            if cmd.is_protected:
                passed += 1
                continue

            result = verify_command_full(cmd, platform_family, db)

            now = datetime.now(timezone.utc)
            if result["passed"]:
                cmd.status = "verified"
                cmd.verified_at = now
                cmd.verification_notes = "Passed all checks"
                if auto_protect:
                    cmd.is_protected = True
                    cmd.protected_at = now
                    cmd.protection_reason = "Auto-protected after passing verification"
                passed += 1
            else:
                cmd.status = "flagged"
                cmd.flagged_at = now
                issues = []
                for level in ("syntax", "safety", "cross_reference", "semantic_quality", "regex"):
                    check = result[level]
                    if check["result"] == "fail":
                        issues.append(check["message"])
                cmd.flag_reason = "; ".join(issues)
                cmd.verification_notes = json.dumps(result, default=str)
                failed += 1

        # Update benchmark
        if failed == 0 and total > 0:
            benchmark.verification_status = "completed"
            benchmark.is_ready = True
        elif total == 0:
            benchmark.verification_status = "completed"
        else:
            benchmark.verification_status = "completed_with_issues"

        db.commit()
        logger.info(
            "Verification completed for benchmark %d: %d/%d passed",
            benchmark_id, passed, total,
        )

    except Exception as exc:
        logger.error("Verification failed for benchmark %d: %s", benchmark_id, exc, exc_info=True)
        db.rollback()
        try:
            benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
            if benchmark:
                benchmark.verification_status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
