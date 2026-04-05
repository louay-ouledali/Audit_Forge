#!/usr/bin/env python3
"""Differential benchmarking CI tool.

Runs audit commands against a "hardened" and a "default" Docker container
to identify broken commands: a PASS on default + PASS on hardened usually
means the command isn't actually checking anything useful.

This is a BUILD-TIME / CI tool — it requires Docker but is NOT shipped
as a runtime dependency.

Usage::

    python -m backend.tools.differential_benchmark \\
        --pack backend/preloaded/postgresql_16_v1.1.0.auditforge.json \\
        --default-image postgres:16 \\
        --hardened-image my-hardened-pg16 \\
        --report test-targets/reports/diff_pg16.md

Or programmatically::

    from backend.tools.differential_benchmark import run_differential
    results = await run_differential(pack_path, default_img, hardened_img)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _docker_exec(container: str, cmd: str, timeout: int = 15) -> tuple[str, str, int]:
    """Execute a command in a running Docker container. Returns (stdout, stderr, exit_code)."""
    try:
        result = subprocess.run(
            ["docker", "exec", container, "bash", "-c", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except Exception as exc:
        return "", str(exc), -1


def _docker_sql(container: str, cmd: str, platform: str, timeout: int = 15) -> tuple[str, str, int]:
    """Execute a SQL command in a running Docker container via the platform's CLI."""
    if "postgresql" in platform or "pg" in platform:
        wrapped = f"psql -U postgres -t -A -c \"{cmd}\""
    elif "mysql" in platform:
        wrapped = f"mysql -u root -e \"{cmd}\" --skip-column-names"
    elif "mssql" in platform:
        wrapped = f"/opt/mssql-tools*/bin/sqlcmd -S localhost -U sa -P 'AuditForge!2024' -Q \"{cmd}\" -h -1 -W"
    elif "mongo" in platform:
        wrapped = f"mongosh --quiet --eval '{cmd}'"
    else:
        wrapped = cmd

    return _docker_exec(container, wrapped, timeout)


async def run_differential(
    pack_path: str,
    default_container: str,
    hardened_container: str | None = None,
    platform: str = "",
) -> list[dict[str, Any]]:
    """Run differential benchmark and return per-rule results.

    Each result dict has keys:
    ``section_number``, ``title``, ``audit_command``, ``transport``,
    ``default_result``, ``hardened_result``, ``differential_status``.

    Differential statuses:
    - ``GOOD``: FAIL on default, PASS on hardened (command works correctly)
    - ``SUSPICIOUS``: PASS on both (command may not check anything)
    - ``BOTH_FAIL``: FAIL on both (setting may not exist or command broken)
    - ``BOTH_ERROR``: ERROR on both (command is definitely broken)
    - ``DEFAULT_ONLY``: Only ran on default (no hardened container)
    """
    with open(pack_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rules = data.get("rules", [])
    if not platform:
        platform = data.get("platform", "").lower()

    results: list[dict[str, Any]] = []

    for rule in rules:
        cmd = rule.get("audit_command", "")
        expr = rule.get("expected_output_expression", "")
        transport = rule.get("command_transport", "shell")
        section = rule.get("section_number", "?")
        title = rule.get("title", "")

        if not cmd:
            continue

        # Execute on default container
        if transport == "sql":
            d_stdout, d_stderr, d_exit = _docker_sql(default_container, cmd, platform)
        else:
            d_stdout, d_stderr, d_exit = _docker_exec(default_container, cmd)

        d_status = _classify_output(d_stdout, d_stderr, d_exit, expr)

        # Execute on hardened container (if available)
        h_status = None
        if hardened_container:
            if transport == "sql":
                h_stdout, h_stderr, h_exit = _docker_sql(hardened_container, cmd, platform)
            else:
                h_stdout, h_stderr, h_exit = _docker_exec(hardened_container, cmd)
            h_status = _classify_output(h_stdout, h_stderr, h_exit, expr)

        # Determine differential status
        if not hardened_container:
            diff_status = "DEFAULT_ONLY"
        elif d_status == "ERROR" and h_status == "ERROR":
            diff_status = "BOTH_ERROR"
        elif d_status == "FAIL" and h_status == "PASS":
            diff_status = "GOOD"
        elif d_status == "PASS" and h_status == "PASS":
            diff_status = "SUSPICIOUS"
        elif d_status == "FAIL" and h_status == "FAIL":
            diff_status = "BOTH_FAIL"
        else:
            diff_status = f"{d_status}/{h_status}"

        results.append({
            "section_number": section,
            "title": title,
            "audit_command": cmd[:200],
            "transport": transport,
            "default_result": d_status,
            "hardened_result": h_status,
            "differential_status": diff_status,
            "default_output": (d_stdout or d_stderr)[:200],
        })

    return results


def _classify_output(stdout: str, stderr: str, exit_code: int, expr: str) -> str:
    """Classify command output as PASS, FAIL, or ERROR."""
    if exit_code == -1 or "TIMEOUT" in stderr:
        return "ERROR"
    if exit_code != 0 and not stdout.strip():
        return "ERROR"

    output = stdout.strip()
    if not output and not expr:
        return "ERROR"

    # Quick expression evaluation
    if not expr:
        return "PASS" if output else "ERROR"

    try:
        from backend.core.comparison_engine import evaluate_expression
        result = evaluate_expression(output, expr)
        return "PASS" if result else "FAIL"
    except Exception:
        return "PASS" if output else "ERROR"


def generate_report(results: list[dict[str, Any]], pack_name: str) -> str:
    """Generate a Markdown report from differential results."""
    lines = [
        f"# Differential Benchmark Report: {pack_name}",
        "",
        f"Total rules tested: {len(results)}",
        "",
    ]

    # Summary counts
    counts: dict[str, int] = {}
    for r in results:
        status = r["differential_status"]
        counts[status] = counts.get(status, 0) + 1

    lines.append("## Summary")
    lines.append("")
    lines.append("| Status | Count | Meaning |")
    lines.append("|--------|-------|---------|")
    status_meanings = {
        "GOOD": "Command correctly distinguishes default vs hardened",
        "SUSPICIOUS": "PASS on both — may not check anything useful",
        "BOTH_FAIL": "FAIL on both — setting may not exist",
        "BOTH_ERROR": "ERROR on both — command is broken",
        "DEFAULT_ONLY": "Only tested on default container",
    }
    for status, count in sorted(counts.items()):
        meaning = status_meanings.get(status, "")
        lines.append(f"| {status} | {count} | {meaning} |")

    # Detailed issues
    suspicious = [r for r in results if r["differential_status"] == "SUSPICIOUS"]
    broken = [r for r in results if r["differential_status"] == "BOTH_ERROR"]

    if broken:
        lines.append("")
        lines.append("## Broken Commands (BOTH_ERROR)")
        lines.append("")
        for r in broken:
            lines.append(f"- **{r['section_number']}** {r['title']}")
            lines.append(f"  - `{r['audit_command']}`")

    if suspicious:
        lines.append("")
        lines.append("## Suspicious Commands (PASS on both)")
        lines.append("")
        for r in suspicious:
            lines.append(f"- **{r['section_number']}** {r['title']}")
            lines.append(f"  - `{r['audit_command']}`")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Differential CIS benchmark testing")
    parser.add_argument("--pack", required=True, help="Path to .auditforge.json pack file")
    parser.add_argument("--default-container", required=True, help="Docker container name (default config)")
    parser.add_argument("--hardened-container", help="Docker container name (hardened config)")
    parser.add_argument("--platform", default="", help="Platform override")
    parser.add_argument("--report", help="Output report path (.md)")
    args = parser.parse_args()

    results = asyncio.run(run_differential(
        args.pack, args.default_container, args.hardened_container, args.platform,
    ))

    pack_name = os.path.basename(args.pack)
    report = generate_report(results, pack_name)
    print(report)

    if args.report:
        os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nReport written to {args.report}")


if __name__ == "__main__":
    main()
