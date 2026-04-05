"""`auditforge run` — full pipeline: client → mission → targets → scan → report."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from cli import api_client as api
from cli.display import print_header, print_step, print_success, print_error, print_summary_table

console = Console()

TOTAL_STEPS = 8


def run(
    client: str = typer.Option(..., "--client", "-c", help="Client name (created if not found)"),
    mission: str = typer.Option(..., "--mission", "-m", help="Mission name (created if not found)"),
    targets: str = typer.Option(..., "--targets", "-t", help="Comma-separated IPs or hostnames"),
    benchmark: Optional[str] = typer.Option(None, "--benchmark", "-b", help="Benchmark name for auto-match (optional)"),
    report: str = typer.Option("pdf", "--report", "-r", help="Report format: pdf, html, excel"),
    output: str = typer.Option(".", "--output", "-o", help="Output directory for report"),
) -> None:
    """Run the full audit pipeline: client → mission → targets → scan → report."""
    print_header("Forge CLI — Full Pipeline")
    step = 0

    # 1. Resolve/create client
    step += 1
    print_step(step, TOTAL_STEPS, "Resolving client...")
    clients_resp = api.get("/clients")
    clients_list = clients_resp if isinstance(clients_resp, list) else clients_resp.get("data", [])
    client_obj = next((c for c in clients_list if c["name"].lower() == client.lower()), None)
    if not client_obj:
        client_obj = api.post("/clients", json={"name": client})
        print_success(f"Created client: {client} (ID {client_obj['id']})")
    else:
        print_success(f"Found client: {client} (ID {client_obj['id']})")

    # 2. Resolve/create mission
    step += 1
    print_step(step, TOTAL_STEPS, "Resolving mission...")
    missions_resp = api.get("/missions", client_id=client_obj["id"])
    missions_list = missions_resp if isinstance(missions_resp, list) else missions_resp.get("data", [])
    mission_obj = next((m for m in missions_list if m["name"].lower() == mission.lower()), None)
    if not mission_obj:
        mission_obj = api.post("/missions", json={"name": mission, "client_id": client_obj["id"]})
        print_success(f"Created mission: {mission} (ID {mission_obj['id']})")
    else:
        print_success(f"Found mission: {mission} (ID {mission_obj['id']})")
    mission_id = mission_obj["id"]

    # 3. Resolve/create targets
    step += 1
    target_ips = [t.strip() for t in targets.split(",") if t.strip()]
    print_step(step, TOTAL_STEPS, f"Resolving {len(target_ips)} target(s)...")
    existing = api.get(f"/targets?mission_id={mission_id}")
    existing_list = existing if isinstance(existing, list) else existing.get("data", [])
    existing_ips = {t.get("ip_address") for t in existing_list}

    target_objs = []
    for ip in target_ips:
        if ip in existing_ips:
            t_obj = next(t for t in existing_list if t.get("ip_address") == ip)
            target_objs.append(t_obj)
        else:
            t_obj = api.post("/targets", json={
                "ip_address": ip,
                "hostname": ip,
                "mission_id": mission_id,
                "client_id": client_obj["id"],
            })
            target_objs.append(t_obj)
    print_success(f"{len(target_objs)} target(s) ready")

    # 4. Auto-match benchmarks
    step += 1
    print_step(step, TOTAL_STEPS, "Matching benchmarks to targets...")
    for t_obj in target_objs:
        try:
            api.post(f"/targets/{t_obj['id']}/benchmark-match")
        except Exception:
            pass
    print_success("Benchmark auto-match complete")

    # 5. Launch batch scan
    step += 1
    print_step(step, TOTAL_STEPS, "Launching batch scan...")
    target_ids = [t["id"] for t in target_objs]
    try:
        batch = api.post("/scans/batch", json={
            "mission_id": mission_id,
            "target_ids": target_ids,
        })
        batch_id = batch.get("batch_id") or batch.get("id")
    except Exception as e:
        print_error(f"Batch scan failed: {e}")
        raise typer.Exit(1)
    print_success(f"Batch scan started (batch {batch_id})")

    # 6. Poll progress
    step += 1
    print_step(step, TOTAL_STEPS, "Waiting for scan completion...")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning...", total=len(target_ids))
        completed_count = 0
        while completed_count < len(target_ids):
            time.sleep(3)
            try:
                status = api.get(f"/scans/batch/{batch_id}/status")
                items = status.get("items", status.get("scans", []))
                done = sum(1 for s in items if s.get("status") in ("completed", "failed", "imported"))
                progress.update(task, completed=done)
                completed_count = done
            except Exception:
                time.sleep(5)
    print_success("All scans finished")

    # 7. Generate report
    step += 1
    print_step(step, TOTAL_STEPS, f"Generating {report.upper()} report...")
    try:
        report_resp = api.post("/reports/generate", json={
            "mission_id": mission_id,
            "format": report,
        })
        report_id = report_resp.get("report_id") or report_resp.get("id")
        print_success(f"Report generated (ID {report_id})")
    except Exception as e:
        print_error(f"Report generation failed: {e}")
        report_id = None

    # 8. Download report
    step += 1
    out_dir = Path(output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if report_id:
        print_step(step, TOTAL_STEPS, "Downloading report...")
        try:
            filepath = api.stream_download(f"/reports/{report_id}/download", str(out_dir))
            print_success(f"Report saved: {filepath}")
        except Exception as e:
            print_error(f"Download failed: {e}")
    else:
        print_step(step, TOTAL_STEPS, "Skipping download (no report)")

    # Summary
    scans_resp = api.get("/scans", mission_id=mission_id)
    scans_list = scans_resp if isinstance(scans_resp, list) else scans_resp.get("data", [])
    total_pass = sum(s.get("passed", 0) for s in scans_list)
    total_fail = sum(s.get("failed", 0) for s in scans_list)
    total_rules = total_pass + total_fail
    compliance = (total_pass / total_rules * 100) if total_rules > 0 else 0

    print_summary_table({
        "Client": client,
        "Mission": mission,
        "Targets": len(target_ids),
        "Scans": len(scans_list),
        "Passed": total_pass,
        "Failed": total_fail,
        "Compliance": f"{compliance:.1f}%",
    })
