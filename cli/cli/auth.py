"""Login / authentication flow."""
from __future__ import annotations

import httpx
from rich.console import Console

from cli.config import save_config, save_credentials

console = Console()


def do_login(server: str, username: str, password: str) -> None:
    """Authenticate with the AuditForge backend and store credentials."""
    server = server.rstrip("/")
    url = f"{server}/api/auth/login"

    console.print(f"[dim]Connecting to {server}...[/dim]")
    try:
        r = httpx.post(url, json={"username": username, "password": password}, timeout=15.0)
        r.raise_for_status()
    except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectTimeout):
        console.print(f"[red]Cannot connect to {server}. Is the backend running?[/red]")
        raise SystemExit(1)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            console.print("[red]Invalid credentials.[/red]")
        else:
            console.print(f"[red]Login failed: {e.response.status_code} {e.response.text}[/red]")
        raise SystemExit(1)

    data = r.json()
    save_config({"server_url": server})
    save_credentials(data["access_token"], data.get("user", {}))
    user_name = data.get("user", {}).get("full_name") or data.get("user", {}).get("username") or username
    console.print(f"[green]Logged in as [bold]{user_name}[/bold]. Token stored in ~/.auditforge/[/green]")
