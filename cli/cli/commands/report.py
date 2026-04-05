"""`auditforge report` — generate and download a report for a mission."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from cli import api_client as api
from cli.display import print_header, print_success, print_error

console = Console()


def report(
    mission: int = typer.Option(..., "--mission", "-m", help="Mission ID"),
    format: str = typer.Option("pdf", "--format", "-f", help="Report format: pdf, html, excel"),
    output: str = typer.Option(".", "--output", "-o", help="Output directory"),
) -> None:
    """Generate and download a report for a mission."""
    print_header("Forge CLI — Report")

    console.print(f"  Generating {format.upper()} report for mission {mission}...")
    try:
        resp = api.post("/reports/generate", json={"mission_id": mission, "format": format})
        report_id = resp.get("report_id") or resp.get("id")
        print_success(f"Report generated (ID {report_id})")
    except Exception as e:
        print_error(f"Generation failed: {e}")
        raise typer.Exit(1)

    out_dir = Path(output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        filepath = api.stream_download(f"/reports/{report_id}/download", str(out_dir))
        print_success(f"Saved: {filepath}")
    except Exception as e:
        print_error(f"Download failed: {e}")
        raise typer.Exit(1)
