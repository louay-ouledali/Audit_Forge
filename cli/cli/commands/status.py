"""`auditforge status` — check scan or batch progress."""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from cli import api_client as api
from cli.display import print_header, print_scan_table

console = Console()


def status(
    scan_id: Optional[int] = typer.Option(None, "--scan", "-s", help="Scan ID to check"),
    batch_id: Optional[int] = typer.Option(None, "--batch", "-b", help="Batch ID to check"),
    mission_id: Optional[int] = typer.Option(None, "--mission", "-m", help="Mission ID to list scans"),
) -> None:
    """Check scan, batch, or mission progress."""
    print_header("Forge CLI — Status")

    if scan_id:
        s = api.get(f"/scans/{scan_id}")
        print_scan_table([s])
    elif batch_id:
        resp = api.get(f"/scans/batch/{batch_id}/status")
        items = resp.get("items", resp.get("scans", []))
        console.print(f"  Batch {batch_id}: {len(items)} scan(s)")
        print_scan_table(items)
    elif mission_id:
        resp = api.get("/scans", mission_id=mission_id)
        scans = resp if isinstance(resp, list) else resp.get("data", [])
        console.print(f"  Mission {mission_id}: {len(scans)} scan(s)")
        print_scan_table(scans)
    else:
        console.print("[dim]Provide --scan, --batch, or --mission[/dim]")
        raise typer.Exit(1)
