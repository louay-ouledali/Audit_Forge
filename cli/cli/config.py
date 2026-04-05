"""Forge CLI configuration — server URL + token storage."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".auditforge"
CONFIG_FILE = CONFIG_DIR / "config.json"
CREDS_FILE = CONFIG_DIR / "credentials.json"


def _ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save_config(data: dict) -> None:
    _ensure_dir()
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def get_server_url() -> str:
    cfg = load_config()
    url = cfg.get("server_url", "")
    if not url:
        raise SystemExit("[red]Not configured. Run: auditforge login --server URL --username USER --password PASS[/red]")
    return url.rstrip("/")


def load_credentials() -> dict:
    if CREDS_FILE.exists():
        return json.loads(CREDS_FILE.read_text())
    return {}


def save_credentials(token: str, user: dict) -> None:
    _ensure_dir()
    CREDS_FILE.write_text(json.dumps({"access_token": token, "user": user}, indent=2))


def get_token() -> str:
    creds = load_credentials()
    token = creds.get("access_token", "")
    if not token:
        raise SystemExit("[red]Not authenticated. Run: auditforge login[/red]")
    return token
