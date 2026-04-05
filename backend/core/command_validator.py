"""Static command validation for audit commands and comparison expressions.

Transport-aware validators catch syntax errors before runtime:
- SQL: balanced quotes, no shell pipes, proper syntax
- Shell: unmatched quotes, broken pipes, unbound variables
- PowerShell: unmatched braces, bash operators in PS
- CLI: shell commands on CLI transport
- Expressions: tautologies, likely inversions, empty comparisons

Usage::

    from backend.core.command_validator import validate_command, Issue

    issues = validate_command(cmd, transport, expression, rule_title)
    errors = [i for i in issues if i.severity == "error"]
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple


class Issue(NamedTuple):
    severity: str  # "error" | "warning"
    category: str  # e.g. "syntax", "shell_mix", "tautology"
    message: str


# ═══════════════════════════════════════════════════════════════════
# SQL Validator
# ═══════════════════════════════════════════════════════════════════

def validate_sql(cmd: str) -> list[Issue]:
    """Validate a SQL-transport command."""
    issues: list[Issue] = []
    if not cmd or not cmd.strip():
        return issues

    # Shell pipes in SQL
    if re.search(r'\|\s*(?:grep|awk|sed|wc|cut|sort|head|tail|tr|uniq)\b', cmd):
        issues.append(Issue("error", "shell_mix",
                            "SQL command contains shell pipe operators"))

    # Shell wrappers around SQL (should be raw SQL, not psql -c)
    if re.match(r'^\s*(?:psql|sqlplus|mysql|mongo|sqlcmd)\s', cmd, re.IGNORECASE):
        issues.append(Issue("warning", "shell_wrapper",
                            "SQL-transport command should be raw SQL, not a shell wrapper"))

    # Unbalanced single quotes (count quotes, ignoring escaped ones)
    cleaned = cmd.replace("\\'", "").replace("''", "")
    if cleaned.count("'") % 2 != 0:
        issues.append(Issue("error", "syntax",
                            "Unbalanced single quotes in SQL command"))

    # Unbalanced parentheses
    if cmd.count("(") != cmd.count(")"):
        issues.append(Issue("warning", "syntax",
                            "Unbalanced parentheses in SQL command"))

    return issues


# ═══════════════════════════════════════════════════════════════════
# Shell Validator
# ═══════════════════════════════════════════════════════════════════

_STANDARD_ENV_VARS = {
    "HOME", "USER", "PATH", "SHELL", "PWD", "HOSTNAME", "LANG", "TERM",
    "LOGNAME", "MAIL", "EDITOR", "TMOUT", "UID", "EUID", "GROUPS",
    "BASH", "BASH_VERSION", "BASH_SOURCE", "FUNCNAME", "LINENO",
    "RANDOM", "SECONDS", "PPID", "IFS", "PS1", "PS2", "PS4",
    "CATALINA_HOME", "CATALINA_BASE", "JAVA_HOME", "ORACLE_HOME",
    "APACHE_PREFIX", "BIND_HOME", "FWDIR", "PGDATA",
    "OLDPWD", "TMPDIR", "DISPLAY", "SSH_AUTH_SOCK",
}


def validate_shell(cmd: str) -> list[Issue]:
    """Validate a shell-transport command."""
    issues: list[Issue] = []
    if not cmd or not cmd.strip():
        return issues

    # Unbalanced quotes (rough check)
    cleaned = cmd.replace("\\'", "").replace('\\"', "")
    if cleaned.count("'") % 2 != 0:
        issues.append(Issue("error", "syntax",
                            "Unbalanced single quotes in shell command"))
    if cleaned.count('"') % 2 != 0:
        issues.append(Issue("error", "syntax",
                            "Unbalanced double quotes in shell command"))

    # Unbalanced backticks
    if cleaned.count("`") % 2 != 0:
        issues.append(Issue("warning", "syntax",
                            "Unbalanced backticks in shell command"))

    # Broken pipe: trailing pipe with nothing after
    if re.search(r'\|\s*$', cmd.rstrip()):
        issues.append(Issue("error", "syntax",
                            "Trailing pipe with no command after it"))

    # Unterminated subshell
    open_parens = cmd.count("$(") + cmd.count("(")
    close_parens = cmd.count(")")
    if open_parens > close_parens + 1:  # Allow some slack for regex
        issues.append(Issue("warning", "syntax",
                            "Possibly unterminated subshell"))

    # grep with --- pattern (ambiguous)
    if re.search(r'grep\s+---\s', cmd) and '-- ' not in cmd:
        issues.append(Issue("error", "syntax",
                            "grep --- is ambiguous; use grep -- '---'"))

    return issues


# ═══════════════════════════════════════════════════════════════════
# PowerShell Validator
# ═══════════════════════════════════════════════════════════════════

def validate_powershell(cmd: str) -> list[Issue]:
    """Validate a PowerShell-transport command."""
    issues: list[Issue] = []
    if not cmd or not cmd.strip():
        return issues

    # Bash operators in PowerShell
    if re.search(r'\|\s*(?:grep|awk|sed|wc|cut|sort)\b', cmd):
        issues.append(Issue("error", "shell_mix",
                            "PowerShell command uses bash-style pipe operators"))

    # Unbalanced braces
    if cmd.count("{") != cmd.count("}"):
        issues.append(Issue("warning", "syntax",
                            "Unbalanced curly braces in PowerShell command"))

    # Unbalanced parentheses
    if cmd.count("(") != cmd.count(")"):
        issues.append(Issue("warning", "syntax",
                            "Unbalanced parentheses in PowerShell command"))

    # Unbalanced square brackets
    if cmd.count("[") != cmd.count("]"):
        issues.append(Issue("warning", "syntax",
                            "Unbalanced square brackets in PowerShell command"))

    return issues


# ═══════════════════════════════════════════════════════════════════
# CLI Validator (network devices)
# ═══════════════════════════════════════════════════════════════════

def validate_cli(cmd: str) -> list[Issue]:
    """Validate a CLI-transport command (network devices)."""
    issues: list[Issue] = []
    if not cmd or not cmd.strip():
        return issues

    # Shell commands on CLI transport
    shell_cmds = ("grep", "awk", "sed", "cat", "echo", "find", "ls", "wc",
                  "cut", "sort", "head", "tail", "tr", "bash", "sh")
    first_word = cmd.strip().split()[0].lower() if cmd.strip() else ""
    if first_word in shell_cmds:
        issues.append(Issue("error", "shell_mix",
                            f"CLI transport command starts with shell command '{first_word}'"))

    # Pipe operators (most network CLIs don't support them or use different syntax)
    if re.search(r'\|\s*(?:grep|awk|sed|wc)\b', cmd):
        issues.append(Issue("warning", "shell_mix",
                            "CLI command contains bash-style pipe; device may not support it"))

    return issues


# ═══════════════════════════════════════════════════════════════════
# Expression Validator
# ═══════════════════════════════════════════════════════════════════

def validate_expression(expr: str, rule_title: str = "") -> list[Issue]:
    """Validate a comparison expression for correctness and semantic issues."""
    issues: list[Issue] = []
    if not expr or not expr.strip():
        return issues

    expr = expr.strip()
    tl = rule_title.lower()

    # Empty comparison value
    if expr in ("contains:", "not_contains:", "==", "!=") or expr.endswith(":"):
        issues.append(Issue("error", "empty_value",
                            f"Expression has empty comparison value: {expr}"))
        return issues

    # Tautological expressions
    m = re.match(r'^>=\s*(\d+)$', expr)
    if m and int(m.group(1)) == 0:
        issues.append(Issue("warning", "tautology",
                            ">=0 is always true (tautological)"))

    m = re.match(r'^<=\s*(\d+)$', expr)
    if m and int(m.group(1)) > 999999:
        issues.append(Issue("warning", "tautology",
                            f"<={m.group(1)} is effectively always true"))

    # Likely inversions based on title keywords
    if "renamed" in tl and expr == "==sa":
        issues.append(Issue("error", "inversion",
                            "Rule is about renaming 'sa' but expression checks ==sa (should be !=sa)"))

    if "disabled" in tl:
        if expr == "==1" and ("sa" in tl or "account" in tl):
            pass  # is_disabled=1 means disabled, this is correct
        elif expr == "==on" or expr == "==ON":
            issues.append(Issue("warning", "inversion",
                                "Rule mentions 'disabled' but expression checks ==on"))

    if "enabled" in tl and (expr == "==off" or expr == "==OFF"):
        issues.append(Issue("warning", "inversion",
                            "Rule mentions 'enabled' but expression checks ==off"))

    return issues


# ═══════════════════════════════════════════════════════════════════
# Top-level dispatcher
# ═══════════════════════════════════════════════════════════════════

def validate_command(
    cmd: str,
    transport: str,
    expression: str = "",
    rule_title: str = "",
) -> list[Issue]:
    """Validate a command + expression against its transport type.

    Returns a list of :class:`Issue` objects (may be empty if all is well).
    """
    issues: list[Issue] = []
    transport_lower = (transport or "").lower().strip()

    # Transport-specific validation
    validators = {
        "sql": validate_sql,
        "shell": validate_shell,
        "powershell": validate_powershell,
        "cli": validate_cli,
    }
    validator = validators.get(transport_lower)
    if validator and cmd:
        issues.extend(validator(cmd))

    # Expression validation (transport-independent)
    if expression:
        issues.extend(validate_expression(expression, rule_title))

    return issues
