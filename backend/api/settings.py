from __future__ import annotations

import io
import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from backend.config import settings as app_config
from backend.core.exceptions import BackupError
from backend.database import Base, get_db, engine
from backend.models.app_settings import AppSettings
from backend.schemas.settings import (
    BackupResponse,
    RestoreResponse,
    SettingsResponse,
    SettingsUpdate,
    SingleSettingResponse,
)

logger = logging.getLogger("auditforge.settings")

router = APIRouter(prefix="/settings", tags=["settings"])

VALID_SETTING_KEYS = {
    "llm_mode",
    "llm_offline_model",
    "llm_ollama_url",
    "llm_online_provider",
    "llm_online_api_key_encrypted",
    "llm_online_model",
    "llm_online_base_url",
    "verification_enabled",
    "verification_auto_protect_passing",
    "default_scan_mode",
    "llm_category_detection",
}


@router.get("", response_model=SettingsResponse)
def get_all_settings(db: Session = Depends(get_db)) -> dict:
    rows = db.query(AppSettings).all()
    data = {row.key: row.value for row in rows}
    return {"data": data, "message": "success"}


@router.put("", response_model=SettingsResponse)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> dict:
    invalid_keys = set(payload.settings.keys()) - VALID_SETTING_KEYS
    if invalid_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid setting keys: {', '.join(sorted(invalid_keys))}",
        )

    now = datetime.now(timezone.utc)
    for key, value in payload.settings.items():
        existing = db.query(AppSettings).filter(AppSettings.key == key).first()
        if existing:
            existing.value = value
            existing.updated_at = now
        else:
            db.add(AppSettings(key=key, value=value, updated_at=now))
    db.commit()

    rows = db.query(AppSettings).all()
    data = {row.key: row.value for row in rows}
    return {"data": data, "message": "Settings updated"}


@router.get("/{key}", response_model=SingleSettingResponse)
def get_setting(key: str, db: Session = Depends(get_db)) -> dict:
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    return {"data": {row.key: row.value}, "message": "success"}


# ── Database Backup & Restore ─────────────────────────────────


def _get_db_path() -> Path:
    """Resolve the SQLite database file path from the configured URL."""
    url = app_config.resolved_database_url
    if not url.startswith("sqlite:///"):
        raise BackupError("Backup/restore is only supported for SQLite databases")
    return Path(url.replace("sqlite:///", ""))


@router.post("/backup", response_model=BackupResponse)
def create_backup(db: Session = Depends(get_db)):
    """Create a database backup and return it as a downloadable file."""
    db_path = _get_db_path()
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Database file not found")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_filename = f"auditforge_backup_{timestamp}.db"

    try:
        # Ensure all pending writes are flushed
        db.execute(text("PRAGMA wal_checkpoint(FULL)"))
    except Exception:
        pass  # Not critical if WAL checkpoint fails

    # Read the database file into memory
    backup_bytes = db_path.read_bytes()

    return Response(
        content=backup_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{backup_filename}"',
            "X-Backup-Filename": backup_filename,
            "X-Backup-Size": str(len(backup_bytes)),
        },
    )


@router.post("/restore", response_model=RestoreResponse)
async def restore_backup(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Restore the database from an uploaded backup file.

    The uploaded file must be a valid SQLite database.
    """
    db_path = _get_db_path()

    # Read uploaded content
    content = await file.read()
    if len(content) < 100:
        raise HTTPException(status_code=400, detail="Uploaded file is too small to be a valid database")

    # Validate it's a SQLite file (magic bytes: "SQLite format 3\000")
    if not content[:16].startswith(b"SQLite format 3\x00"):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not a valid SQLite database",
        )

    # Validate the backup has the expected tables by opening it in a temp location
    import sqlite3

    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
        Path(tmp_path).write_bytes(content)

        conn = sqlite3.connect(tmp_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        # Check that at least some expected tables exist
        expected_tables = {"benchmarks", "rules", "clients", "missions", "app_settings"}
        found = expected_tables & tables
        if not found:
            raise HTTPException(
                status_code=400,
                detail="Backup file does not contain expected AditForge tables",
            )

        tables_restored = len(tables)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to validate backup file: {exc}",
        )
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    # Close the current DB session and replace the database file
    db.close()

    try:
        # Create a safety backup of the current database
        if db_path.exists():
            safety_backup = db_path.with_suffix(".db.bak")
            shutil.copy2(str(db_path), str(safety_backup))

        # Write the new database
        db_path.write_bytes(content)

        logger.info(
            "Database restored from backup (%d tables, %d bytes)",
            tables_restored, len(content),
        )
    except Exception as exc:
        logger.error("Database restore failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore database: {exc}",
        )

    return RestoreResponse(
        message="Database restored successfully. Please restart the application.",
        tables_restored=tables_restored,
    )
