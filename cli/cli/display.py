"""Rich display helpers — tables, progress bars, panels."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_header(title: str) -> None:
    console.print(Panel(f"[bold yellow]{title}[/bold yellow]", border_style="yellow", expand=False))


def print_step(n: int, total: int, msg: str) -> None:
    console.print(f"  [dim][{n}/{total}][/dim] {msg}")


def print_success(msg: str) -> None:
    console.print(f"  [green]✓[/green] {msg}")


def print_error(msg: str) -> None:
    console.print(f"  [red]✗[/red] {msg}")


def print_summary_table(results: dict) -> None:
    """Print a summary table after a pipeline run."""
    table = Table(title="Pipeline Summary", border_style="yellow")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    for key, val in results.items():
        style = ""
        if key == "Compliance":
            pct = float(str(val).replace("%", ""))
            style = "green" if pct >= 80 else "yellow" if pct >= 60 else "red"
        table.add_row(key, f"[{style}]{val}[/{style}]" if style else str(val))

    console.print()
    console.print(table)


def print_scan_table(scans: list[dict]) -> None:
    table = Table(border_style="dim")
    table.add_column("ID", style="bold")
    table.add_column("Target")
    table.add_column("Benchmark")
    table.add_column("Status")
    table.add_column("Pass", justify="right", style="green")
    table.add_column("Fail", justify="right", style="red")
    table.add_column("Compliance", justify="right")

    for s in scans:
        status_style = {
            "completed": "green", "running": "yellow", "failed": "red", "imported": "cyan"
        }.get(s.get("status", ""), "dim")
        comp = s.get("compliance_percentage")
        comp_str = f"{comp:.1f}%" if comp is not None else "—"
        table.add_row(
            str(s["id"]),
            s.get("target_name") or s.get("target_ip", "—"),
            s.get("benchmark_name", "—"),
            f"[{status_style}]{s.get('status', '—')}[/{status_style}]",
            str(s.get("passed", 0)),
            str(s.get("failed", 0)),
            comp_str,
        )

    console.print(table)
