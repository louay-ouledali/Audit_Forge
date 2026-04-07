"""Forge CLI — AuditForge command-line pipeline automation.

Usage:
    auditforge login --server http://10.0.0.5:8000 --username admin --password auditforge
    auditforge run --client "EY Tunisia" --mission "Q1 2026" --targets 192.168.1.10,192.168.1.20 --report pdf
    auditforge scan --target 42 --benchmark 7
    auditforge report --mission 5 --format pdf --output ./reports
    auditforge status --scan 12
"""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="auditforge",
    help="Forge CLI — AuditForge pipeline automation",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()


@app.command()
def login(
    server: str = typer.Option(..., "--server", "-s", help="AuditForge backend URL"),
    username: str = typer.Option(..., "--username", "-u", help="Username"),
    password: str = typer.Option(..., "--password", "-p", help="Password", hide_input=True),
) -> None:
    """Authenticate with an AuditForge server."""
    from cli.auth import do_login
    do_login(server, username, password)


@app.command()
def run(
    client: str = typer.Option(..., "--client", "-c", help="Client name (created if not found)"),
    mission: str = typer.Option(..., "--mission", "-m", help="Mission name (created if not found)"),
    targets: str = typer.Option(..., "--targets", "-t", help="Comma-separated IPs or hostnames"),
    benchmark: Optional[str] = typer.Option(None, "--benchmark", "-b", help="Benchmark name hint (optional)"),
    report: str = typer.Option("pdf", "--report", "-r", help="Report format: pdf, html, excel"),
    output: str = typer.Option(".", "--output", "-o", help="Output directory for report"),
) -> None:
    """Run the full review pipeline: client → mission → targets → scan → report."""
    from cli.commands.run import run as _run
    _run(client=client, mission=mission, targets=targets, benchmark=benchmark, report=report, output=output)


@app.command()
def scan(
    target: int = typer.Option(..., "--target", "-t", help="Target ID"),
    benchmark: Optional[int] = typer.Option(None, "--benchmark", "-b", help="Benchmark ID"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for completion"),
) -> None:
    """Run a single scan on a target."""
    from cli.commands.scan import scan as _scan
    _scan(target=target, benchmark=benchmark, wait=wait)


@app.command()
def report(
    mission: int = typer.Option(..., "--mission", "-m", help="Mission ID"),
    format: str = typer.Option("pdf", "--format", "-f", help="Report format: pdf, html, excel"),
    output: str = typer.Option(".", "--output", "-o", help="Output directory"),
) -> None:
    """Generate and download a report."""
    from cli.commands.report import report as _report
    _report(mission=mission, format=format, output=output)


@app.command()
def status(
    scan_id: Optional[int] = typer.Option(None, "--scan", "-s", help="Scan ID"),
    batch_id: Optional[int] = typer.Option(None, "--batch", "-b", help="Batch ID"),
    mission_id: Optional[int] = typer.Option(None, "--mission", "-m", help="Mission ID"),
) -> None:
    """Check scan, batch, or mission progress."""
    from cli.commands.status import status as _status
    _status(scan_id=scan_id, batch_id=batch_id, mission_id=mission_id)


if __name__ == "__main__":
    app()
