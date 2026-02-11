"""Verification engine: syntax and safety checks for generated audit commands."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.verification_report import VerificationReport

logger = logging.getLogger("auditforge.verify")

# Dangerous command patterns by platform family
DANGEROUS_LINUX = [
    (r'\brm\s+-', "rm with flags — deletes files"),
    (r'\brm\s+/', "rm on absolute path — deletes files"),
    (r'\bmkdir\b', "mkdir — creates directories"),
    (r'\btouch\b', "touch — creates/modifies files"),
    (r'\bchmod\b', "chmod — changes permissions"),
    (r'\bchown\b', "chown — changes ownership"),
    (r'\bchgrp\b', "chgrp — changes group"),
    (r'\bsed\s+-i\b', "sed -i — in-place file edit"),
    (r'\bsed\s+.*-i\b', "sed with -i flag — in-place file edit"),
    (r'\btee\s', "tee — writes to file"),
    (r'>\s*/', "redirect to absolute path — writes to file"),
    (r'>>', "append redirect — writes to file"),
    (r'\bsystemctl\s+(start|stop|restart|enable|disable|mask|unmask)\b', "systemctl modification"),
    (r'\bservice\s+\S+\s+(start|stop|restart)\b', "service modification"),
    (r'\bapt\b.*\b(install|remove|purge|autoremove)\b', "apt package modification"),
    (r'\bapt-get\b.*\b(install|remove|purge)\b', "apt-get package modification"),
    (r'\byum\b.*\b(install|remove|erase|update)\b', "yum package modification"),
    (r'\bdnf\b.*\b(install|remove|erase|update)\b', "dnf package modification"),
    (r'\buseradd\b', "useradd — creates user"),
    (r'\buserdel\b', "userdel — deletes user"),
    (r'\busermod\b', "usermod — modifies user"),
    (r'\bpasswd\b', "passwd — changes password"),
    (r'\biptables\s+-[ADIFX]\b', "iptables modification"),
    (r'\bufw\s+(allow|deny|enable|disable|delete)\b', "ufw modification"),
    (r'\bdd\s+', "dd — raw disk write potentially"),
    (r'\bmkfs\b', "mkfs — formats filesystem"),
    (r'\breboot\b', "reboot — restarts system"),
    (r'\bshutdown\b', "shutdown — shuts down system"),
    (r'\bpoweroff\b', "poweroff — shuts down system"),
    (r'\bkill\b', "kill — terminates process"),
    (r'\bkillall\b', "killall — terminates processes"),
    (r'\bsysctl\s+-w\b', "sysctl -w — modifies kernel parameter"),
]

DANGEROUS_WINDOWS = [
    (r'Set-ItemProperty', "Set-ItemProperty — modifies registry"),
    (r'New-ItemProperty', "New-ItemProperty — creates registry value"),
    (r'Remove-ItemProperty', "Remove-ItemProperty — deletes registry value"),
    (r'Remove-Item', "Remove-Item — deletes files/registry"),
    (r'New-Item', "New-Item — creates files/directories/registry"),
    (r'Set-Content', "Set-Content — writes to file"),
    (r'Add-Content', "Add-Content — appends to file"),
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

DANGEROUS_SQL = [
    (r'\bDROP\b', "DROP — destroys database objects"),
    (r'\bALTER\b', "ALTER — modifies database objects"),
    (r'\bCREATE\b', "CREATE — creates database objects"),
    (r'\bINSERT\b', "INSERT — adds data"),
    (r'\bUPDATE\b', "UPDATE — modifies data"),
    (r'\bDELETE\b', "DELETE — removes data"),
    (r'\bTRUNCATE\b', "TRUNCATE — removes all data"),
    (r'\bGRANT\b', "GRANT — modifies permissions"),
    (r'\bREVOKE\b', "REVOKE — modifies permissions"),
    (r'\bSHUTDOWN\b', "SHUTDOWN — shuts down database"),
]

DANGEROUS_NETWORK = [
    (r'\bconfigure\s+terminal\b', "Enters configuration mode"),
    (r'\bconf\s+t\b', "Enters configuration mode (shorthand)"),
    (r'\bno\s+', "no — negates/removes configuration"),
    (r'\bwrite\s+memory\b', "Writes configuration to flash"),
    (r'\breload\b', "Reloads device"),
    (r'\bshutdown\b', "Shuts down interface"),
    (r'\bset\s', "set — adds configuration"),
    (r'\bdelete\s', "delete — removes configuration"),
    (r'\bcommit\b', "commit — applies configuration changes"),
    (r'\bconfig\s', "config — enters configuration mode"),
    (r'\bunset\s', "unset — removes configuration"),
]

PLATFORM_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "linux": DANGEROUS_LINUX,
    "windows": DANGEROUS_WINDOWS,
    "database": DANGEROUS_SQL,
    "network": DANGEROUS_NETWORK,
}

# Patterns that indicate a command still contains unresolved placeholders
# NOTE: \{...\} is excluded because auditpol GUIDs like {0cce923f-69ae-11d9-bed3-505054503030} are real.
# Instead we match only obvious placeholders e.g. {PLACEHOLDER}, {your_value}, {VALUE_HERE}
PLACEHOLDER_PATTERNS = [
    r'\{[A-Z_]{3,}\}',         # {PLACEHOLDER}, {VALUE_HERE}
    r'\{your_\w+\}',           # {your_value}, {your_path}
    r'<[A-Z_]{3,}>',             # <PLACEHOLDER>, <VALUE_HERE>
    r'<your_\w+>',              # <your_value>
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

    return {"result": "pass", "message": "Syntax OK"}


def _check_safety(audit_command: str | None, platform_family: str) -> dict:
    """Level 2: Safety check. Returns {result: str, message: str, details: list}."""
    if not audit_command or not audit_command.strip():
        return {"result": "fail", "message": "No command to check", "details": []}

    stripped = audit_command.strip()
    patterns = PLATFORM_PATTERNS.get(platform_family, DANGEROUS_LINUX)
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
    patterns = PLATFORM_PATTERNS.get(platform_family, DANGEROUS_LINUX)
    for pattern, description in patterns:
        if re.search(pattern, stripped, re.IGNORECASE):
            issues.append({"type": "safety", "message": f"Dangerous pattern: {description}"})

    return {"passed": len(issues) == 0, "issues": issues}


def verify_regex(regex_str: str | None) -> dict:
    """Verify that a regex pattern is valid Python regex.
    
    Empty/None regex is acceptable — not every audit command needs a pass/fail pattern.
    """
    if not regex_str or not regex_str.strip():
        return {"valid": True, "error": None}  # optional field
    try:
        re.compile(regex_str)
        return {"valid": True, "error": None}
    except re.error as e:
        return {"valid": False, "error": str(e)}


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

    # Regex validation
    regex_result = verify_regex(cmd.expected_output_regex)
    regex_check = {
        "result": "pass" if regex_result["valid"] else "fail",
        "message": "Valid regex" if regex_result["valid"] else f"Invalid regex: {regex_result['error']}",
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
                for level in ("syntax", "safety", "cross_reference", "regex"):
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
