"""`auditforge scan` — run a single scan on a target."""
from __future__ import annotations

import time
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from cli import api_client as api
from cli.display import print_header, print_success, print_error, print_scan_table

console = Console()


def scan(
    target: int = typer.Option(..., "--target", "-t", help="Target ID"),
    benchmark: Optional[int] = typer.Option(None, "--benchmark", "-b", help="Benchmark ID (uses auto-matched if omitted)"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for scan completion"),
) -> None:
    """Run a single scan on a target."""
    print_header("Forge CLI — Scan")

    payload: dict = {"target_id": target}
    if benchmark:
        payload["benchmark_id"] = benchmark

    try:
        result = api.post("/scans", json=payload)
        scan_id = result.get("id") or result.get("scan_id")
        print_success(f"Scan started (ID {scan_id})")
    except Exception as e:
        print_error(f"Failed to start scan: {e}")
        raise typer.Exit(1)

    if not wait:
        console.print(f"[dim]Use: auditforge status --scan {scan_id}[/dim]")
        return

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        progress.add_task("Scanning...", total=None)
        while True:
            time.sleep(3)
            try:
                s = api.get(f"/scans/{scan_id}")
                status = s.get("status", "unknown")
                if status in ("completed", "failed", "imported"):
                    break
            except Exception:
                time.sleep(5)

    s = api.get(f"/scans/{scan_id}")
    if s.get("status") == "completed":
        print_success(f"Scan completed — {s.get('passed', 0)} pass, {s.get('failed', 0)} fail, {s.get('compliance_percentage', 0):.1f}% compliance")
    else:
        print_error(f"Scan ended with status: {s.get('status')}")
    print_scan_table([s])
