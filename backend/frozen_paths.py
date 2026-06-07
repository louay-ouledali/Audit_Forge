"""Centralized path resolution for both development and PyInstaller frozen modes.

In development mode, all paths resolve relative to the project root (parent of backend/).
In frozen mode (PyInstaller --onedir), bundled assets are read from sys._MEIPASS
while writable data (database, .env, backups) goes to %APPDATA%\\AuditForge.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    # PyInstaller --onedir: _MEIPASS is the temporary bundle directory
    BUNDLE_DIR = Path(sys._MEIPASS)
    # Writable user data lives in %APPDATA%\AuditForge
    DATA_ROOT = Path(
        os.environ.get(
            "AUDITFORGE_DATA",
            os.path.join(os.environ.get("APPDATA", Path.home()), "AuditForge"),
        )
    )
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
else:
    # Development: project root is one level above backend/
    BUNDLE_DIR = Path(__file__).resolve().parent.parent
    DATA_ROOT = BUNDLE_DIR

# Read-only bundled assets
BACKEND_DIR = BUNDLE_DIR / "backend"
TEMPLATE_DIR = BACKEND_DIR / "templates"
PRELOADED_DIR = BACKEND_DIR / "preloaded"
ALEMBIC_DIR = BACKEND_DIR / "alembic"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
SCRIPTS_DIR = BACKEND_DIR / "scripts"
CORE_DIR = BACKEND_DIR / "core"
FRONTEND_DIST = BUNDLE_DIR / "frontend" / "dist"

# Writable runtime paths
DB_DIR = DATA_ROOT / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = DATA_ROOT / ".env"
