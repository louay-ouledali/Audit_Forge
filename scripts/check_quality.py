#!/usr/bin/env python3
"""Benchmark quality checker — validates all rules/commands in the database.

Checks every benchmark (or a specific one) for:
  - Missing audit commands
  - Empty/null expected output expressions
  - Malformed expected output expressions (bad operators)
  - Platform mismatches (PowerShell on Linux, Bash on Windows)
  - Duplicate commands across rules
  - Suspiciously short commands (< 10 chars)
  - Commands with common LLM hallucination patterns
  - Missing remediation commands
  - Remediation commands identical to audit commands

Usage
-----
    # Check all benchmarks
    python scripts/check_quality.py

    # Check specific benchmark
    python scripts/check_quality.py --benchmark-id 8

    # Output JSON report
    python scripts/check_quality.py --json

    # Only show errors (no warnings)
    python scripts/check_quality.py --errors-only

    # Show commands for manual review
    python scripts/check_quality.py --benchmark-id 8 --show-commands
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal  # noqa: E402
from backend.models.benchmark import Benchmark  # noqa: E402
from backend.models.rule import Rule  # noqa: E402
from backend.models.rule_command import RuleCommand  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
#  Severity levels
# ═══════════════════════════════════════════════════════════════════════════════

class Severity:
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


# ═══════════════════════════════════════════════════════════════════════════════
#  Issue dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class Issue:
    __slots__ = ("severity", "section", "field", "message", "detail")

    def __init__(self, severity: str, section: str, field: str, message: str, detail: str = ""):
        self.severity = severity
        self.section = section
        self.field = field
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        d = {"severity": self.severity, "section": self.section, "field": self.field, "message": self.message}
        if self.detail:
            d["detail"] = self.detail
        return d

    def __str__(self) -> str:
        prefix = f"[{self.severity}] {self.section} | {self.field}: {self.message}"
        if self.detail:
            return f"{prefix}\n         {self.detail}"
        return prefix


# ═══════════════════════════════════════════════════════════════════════════════
#  Validation patterns
# ═══════════════════════════════════════════════════════════════════════════════

# Valid expected_output_regex operators
VALID_EXPRESSION_PATTERNS = [
    r"^>=\s*\d+",          # >=24
    r"^<=\s*\d+",          # <=365
    r"^==\s*.+",           # ==1, ==Enabled
    r"^!=\s*.+",           # !=0
    r"^not_empty$",
    r"^contains:",
    r"^not_contains:",
    r"^regex:",
    r"^exists$",
    r"^not_exists$",
]

# PowerShell indicators (avoid matching bash $1, $2, awk variables)
PS_PATTERNS = [
    r"(?<![-/])Get-\w+", r"(?<![-/])Set-\w+", r"(?<![-/])New-\w+", r"(?<![-/])Remove-\w+",
    r"\bInvoke-\w+", r"\bTest-\w+", r"\bImport-\w+", r"\bExport-\w+",
    r"\$[A-Z][A-Za-z_]\w{2,}", r"\bWrite-\w+", r"\bSelect-Object\b", r"\bWhere-Object\b",
    r"\bForEach-Object\b", r"\|\s*Where\b", r"\|\s*Select\b",
    r"\bnet\s+(accounts|user|localgroup)\b", r"\bauditpol\b", r"\bsecedit\b",
    r"\bREG QUERY\b", r"\bHKLM:\\", r"\bErrorAction\b",
]

# Bash/Linux indicators
BASH_PATTERNS = [
    r"\bgrep\b", r"\bawk\b", r"\bsed\b", r"\bcat\s+/", r"\bfind\s+/",
    r"\bsystemctl\b", r"\bsysctl\b", r"\bufw\b", r"\biptables\b",
    r"\bapt\b", r"\byum\b", r"\bdnf\b", r"\bchmod\b", r"\bchown\b",
    r"/etc/\w+", r"\bsudo\b", r"\bwhoami\b", r"\bstat\s",
    r"\bdpkg", r"\brpm\b", r"\bmodprobe\b", r"\blsmod\b", r"\bss\s+-",
    r"\bpasswd\b", r"\bcut\b", r"\bsort\b", r"\buniq\b", r"\bxargs\b",
    r"\bcomm\b", r"\bfindmnt\b", r"\bmount\b", r"\bfirewall-cmd\b",
    r"\becho\s+\$", r"\bTMOUT\b", r"\bjournalctl\b",
]

# SQL indicators
SQL_PATTERNS = [
    r"\bSELECT\b", r"\bFROM\b", r"\bWHERE\b", r"\bSHOW\b",
    r"\bEXEC\b", r"\bsp_configure\b", r"\bALTER\b", r"\bCREATE\b",
]

# Network device CLI indicators
NETWORK_PATTERNS = [
    r"\bshow\s+(running-config|ip|version|interface|access-list|crypto)\b",
    r"\bget\s+(system|firewall|vpn|router)\b",
    r"\bdiag\b", r"\bexecute\b",
]

# Common LLM hallucination patterns in commands
HALLUCINATION_PATTERNS = [
    (r"<placeholder>|<insert.*?>|<your.*?>|(?<!\.)\.\.\.(?: |$)", "Contains placeholder text"),
    (r"(?i)\bTODO\b|\bFIXME\b|\bHACK\b|\bXXX\b", "Contains TODO/FIXME marker"),
    (r"(?i)example\.com|test\.com|\bfoo\b|\bbar\b|\bbaz\b", "Contains example/test values"),
    (r"^\s*#\s", "Command starts with a comment"),
    (r"(?i)replace\s+with|change\s+this|modify\s+as\s+needed", "Contains instructional text"),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Checker functions
# ═══════════════════════════════════════════════════════════════════════════════

def detect_platform(command: str) -> str:
    """Guess the platform of a command: 'windows', 'linux', 'sql', 'network', 'unknown'."""
    if not command:
        return "unknown"

    ps_score = sum(1 for p in PS_PATTERNS if re.search(p, command, re.IGNORECASE))
    bash_score = sum(1 for p in BASH_PATTERNS if re.search(p, command, re.IGNORECASE))
    sql_score = sum(1 for p in SQL_PATTERNS if re.search(p, command, re.IGNORECASE))
    net_score = sum(1 for p in NETWORK_PATTERNS if re.search(p, command, re.IGNORECASE))

    scores = {"windows": ps_score, "linux": bash_score, "sql": sql_score, "network": net_score}
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[best] == 0:
        return "unknown"
    return best


def check_benchmark(benchmark: Benchmark, rules: list[Rule], *, show_commands: bool = False) -> list[Issue]:
    """Run all quality checks on a single benchmark and its rules."""
    issues: list[Issue] = []
    family = (benchmark.platform_family or "").lower()
    command_hashes: Counter[str] = Counter()
    command_map: dict[str, list[str]] = defaultdict(list)  # hash -> [sections]

    for rule in rules:
        sec = rule.section_number
        cmd = rule.commands  # uselist=False -> RuleCommand or None

        # ── Missing command entirely ─────────────────────────────────────
        if cmd is None:
            issues.append(Issue(Severity.ERROR, sec, "command", "No RuleCommand record exists"))
            continue

        audit_cmd = (cmd.audit_command or "").strip()
        expression = (cmd.expected_output_regex or "").strip()
        remediation = (cmd.remediation_command or "").strip()

        # ── Missing audit command ────────────────────────────────────────
        if not audit_cmd:
            issues.append(Issue(Severity.ERROR, sec, "audit_command", "Audit command is empty"))
        else:
            # Track for duplicate detection
            cmd_hash = audit_cmd.lower().strip()
            command_hashes[cmd_hash] += 1
            command_map[cmd_hash].append(sec)

            # Short command check
            if len(audit_cmd) < 10:
                issues.append(Issue(
                    Severity.WARNING, sec, "audit_command",
                    f"Suspiciously short ({len(audit_cmd)} chars)",
                    detail=audit_cmd[:100],
                ))

            # Platform mismatch check
            detected = detect_platform(audit_cmd)
            if detected != "unknown":
                if family == "windows" and detected == "linux":
                    issues.append(Issue(
                        Severity.ERROR, sec, "audit_command",
                        "Linux/Bash command on a Windows benchmark",
                        detail=audit_cmd[:120],
                    ))
                elif family == "linux" and detected == "windows":
                    issues.append(Issue(
                        Severity.ERROR, sec, "audit_command",
                        "PowerShell/Windows command on a Linux benchmark",
                        detail=audit_cmd[:120],
                    ))
                elif family == "network" and detected in ("windows", "linux"):
                    issues.append(Issue(
                        Severity.WARNING, sec, "audit_command",
                        f"OS-specific ({detected}) command on a network device benchmark",
                        detail=audit_cmd[:120],
                    ))
                elif family == "database" and detected in ("windows", "linux") and not re.search(r"SQL|query|psql|mysql|sqlcmd|mongo", audit_cmd, re.IGNORECASE):
                    issues.append(Issue(
                        Severity.WARNING, sec, "audit_command",
                        f"OS-level ({detected}) command on a database benchmark (may be intentional)",
                        detail=audit_cmd[:120],
                    ))

            # Hallucination check
            for pattern, msg in HALLUCINATION_PATTERNS:
                if re.search(pattern, audit_cmd):
                    issues.append(Issue(
                        Severity.ERROR, sec, "audit_command",
                        f"LLM hallucination pattern: {msg}",
                        detail=audit_cmd[:120],
                    ))
                    break  # one hallucination flag per command

        # ── Expected output expression ───────────────────────────────────
        if not expression:
            issues.append(Issue(
                Severity.WARNING, sec, "expected_output",
                "Expected output expression is empty",
            ))
        else:
            valid = any(re.match(p, expression) for p in VALID_EXPRESSION_PATTERNS)
            if not valid:
                # Might be a raw string match (legacy format)
                issues.append(Issue(
                    Severity.INFO, sec, "expected_output",
                    f"Non-standard expression format: '{expression[:60]}'",
                ))

        # ── Remediation command ──────────────────────────────────────────
        if not remediation:
            issues.append(Issue(
                Severity.INFO, sec, "remediation_command",
                "No remediation command provided",
            ))
        elif remediation.strip() == audit_cmd:
            issues.append(Issue(
                Severity.WARNING, sec, "remediation_command",
                "Remediation command is identical to audit command",
            ))

        # ── Description/title sanity ─────────────────────────────────────
        if not rule.title or len(rule.title.strip()) < 5:
            issues.append(Issue(
                Severity.WARNING, sec, "title",
                f"Title is missing or too short: '{rule.title}'",
            ))

    # ── Duplicate command detection ──────────────────────────────────────
    for cmd_hash, count in command_hashes.items():
        if count > 1 and len(cmd_hash) > 15:  # Ignore very short duplicates
            sections = command_map[cmd_hash]
            issues.append(Issue(
                Severity.WARNING, sections[0], "duplicate",
                f"Same audit command used by {count} rules: {', '.join(sections[:5])}",
                detail=cmd_hash[:100],
            ))

    return issues


# ═══════════════════════════════════════════════════════════════════════════════
#  Report generation
# ═══════════════════════════════════════════════════════════════════════════════

def grade_benchmark(total_rules: int, issues: list[Issue]) -> str:
    """Compute a quality grade from A+ to F."""
    if total_rules == 0:
        return "F"
    errors = sum(1 for i in issues if i.severity == Severity.ERROR)
    warnings = sum(1 for i in issues if i.severity == Severity.WARNING)

    error_pct = errors / total_rules * 100
    warning_pct = warnings / total_rules * 100

    if error_pct == 0 and warning_pct == 0:
        return "A+"
    elif error_pct == 0 and warning_pct <= 5:
        return "A"
    elif error_pct <= 2 and warning_pct <= 10:
        return "B"
    elif error_pct <= 5 and warning_pct <= 20:
        return "C"
    elif error_pct <= 15:
        return "D"
    else:
        return "F"


def print_report(benchmark: Benchmark, issues: list[Issue], *, errors_only: bool = False) -> None:
    """Print a human-readable quality report."""
    total_rules = benchmark.total_rules or 0
    errors = [i for i in issues if i.severity == Severity.ERROR]
    warnings = [i for i in issues if i.severity == Severity.WARNING]
    infos = [i for i in issues if i.severity == Severity.INFO]
    grade = grade_benchmark(total_rules, issues)

    print(f"\n{'=' * 80}")
    print(f"  Benchmark: {benchmark.name} v{benchmark.version}")
    print(f"  Platform:  {benchmark.platform} ({benchmark.platform_family})")
    print(f"  Rules:     {total_rules}")
    print(f"  Phase 1:   {benchmark.phase1_status}  |  Phase 2: {benchmark.phase2_status}")
    print(f"  Grade:     {grade}")
    print(f"  Issues:    {len(errors)} errors, {len(warnings)} warnings, {len(infos)} info")
    print(f"{'=' * 80}")

    if errors_only:
        display = errors
    else:
        display = issues

    if not display:
        print("  No issues found! This benchmark looks clean.")
    else:
        for issue in sorted(display, key=lambda i: (i.section, i.severity)):
            print(f"  {issue}")

    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="AuditForge Benchmark Quality Checker")
    parser.add_argument("--benchmark-id", "-b", type=int, help="Check a specific benchmark (default: all)")
    parser.add_argument("--errors-only", "-e", action="store_true", help="Only show ERROR-level issues")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON report")
    parser.add_argument("--show-commands", "-c", action="store_true", help="Show full command text in output")
    parser.add_argument("--phase2-only", action="store_true", help="Only check benchmarks with Phase 2 completed")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(Benchmark).order_by(Benchmark.id)
        if args.benchmark_id:
            query = query.filter(Benchmark.id == args.benchmark_id)
        if args.phase2_only:
            query = query.filter(Benchmark.phase2_status == "completed")

        benchmarks = query.all()
        if not benchmarks:
            print("No benchmarks found matching criteria.")
            sys.exit(1)

        all_reports: list[dict] = []

        for benchmark in benchmarks:
            rules = (
                db.query(Rule)
                .filter(Rule.benchmark_id == benchmark.id)
                .order_by(Rule.section_number)
                .all()
            )

            issues = check_benchmark(benchmark, rules, show_commands=args.show_commands)

            if args.json:
                errors = [i for i in issues if i.severity == Severity.ERROR]
                warnings = [i for i in issues if i.severity == Severity.WARNING]
                all_reports.append({
                    "benchmark_id": benchmark.id,
                    "name": benchmark.name,
                    "version": benchmark.version,
                    "platform": benchmark.platform,
                    "platform_family": benchmark.platform_family,
                    "total_rules": benchmark.total_rules or 0,
                    "phase1_status": benchmark.phase1_status,
                    "phase2_status": benchmark.phase2_status,
                    "grade": grade_benchmark(benchmark.total_rules or 0, issues),
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                    "info_count": len([i for i in issues if i.severity == Severity.INFO]),
                    "issues": [i.to_dict() for i in issues] if not args.errors_only else [i.to_dict() for i in errors],
                })
            else:
                print_report(benchmark, issues, errors_only=args.errors_only)

        if args.json:
            output = json.dumps(all_reports, indent=2, ensure_ascii=False)
            sys.stdout.buffer.write(output.encode("utf-8"))
            sys.stdout.buffer.write(b"\n")

        # Summary
        if not args.json and len(benchmarks) > 1:
            print(f"\n{'=' * 80}")
            print(f"  SUMMARY: {len(benchmarks)} benchmarks checked")
            print(f"{'=' * 80}")
            for benchmark in benchmarks:
                rules = db.query(Rule).filter(Rule.benchmark_id == benchmark.id).all()
                issues = check_benchmark(benchmark, rules)
                errors = sum(1 for i in issues if i.severity == Severity.ERROR)
                warnings = sum(1 for i in issues if i.severity == Severity.WARNING)
                grade = grade_benchmark(benchmark.total_rules or 0, issues)
                p2 = benchmark.phase2_status or "?"
                name = benchmark.name[:55]
                print(f"  [{grade:>2}] {name:<55} | P2={p2:<10} | {errors} err, {warnings} warn")

    finally:
        db.close()


if __name__ == "__main__":
    main()
