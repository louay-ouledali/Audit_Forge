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
    # Per-task model overrides (optional — leave empty to use the global model)
    "llm_task_phase1_parsing_model",
    "llm_task_phase2_commands_model",
    "llm_task_verification_model",
    "llm_task_reports_model",
    "llm_task_analysis_model",
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


# ── Database Backup & Restore ─────────────────────────────────


def _get_db_path() -> Path:
    """Resolve the SQLite database file path from the configured URL."""
    url = app_config.resolved_database_url
    if not url.startswith("sqlite:///"):
        raise BackupError("Backup/restore is only supported for SQLite databases")
    return Path(url.replace("sqlite:///", ""))


@router.post("/backup")
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
    After writing, the engine pool is disposed and Alembic migrations
    are re-run so the restored schema is brought up to date.
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
                detail="Backup file does not contain expected AuditForge tables",
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

    # ── Replace the database file ─────────────────────────────
    # 1) Close ALL connections (session + engine pool)
    db.close()
    engine.dispose()

    try:
        # Create a safety backup of the current database
        if db_path.exists():
            safety_backup = db_path.with_suffix(".db.bak")
            shutil.copy2(str(db_path), str(safety_backup))

        # Remove WAL/SHM files that could conflict with the restored database
        for suffix in ("-wal", "-shm"):
            wal_path = Path(str(db_path) + suffix)
            if wal_path.exists():
                wal_path.unlink(missing_ok=True)

        # Write the new database
        db_path.write_bytes(content)

        logger.info(
            "Database file replaced from backup (%d tables, %d bytes)",
            tables_restored, len(content),
        )
    except Exception as exc:
        logger.error("Database restore failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore database: {exc}",
        )

    # 2) Run Alembic migrations to bring the restored DB schema up to date
    migration_note = ""
    try:
        from alembic.config import Config
        from alembic import command as alembic_cmd

        alembic_cfg = Config("backend/alembic.ini")
        alembic_cmd.upgrade(alembic_cfg, "head")
        logger.info("Post-restore Alembic migrations completed successfully")
    except Exception as exc:
        logger.warning("Post-restore migration issue: %s — will stamp head", exc)
        # If upgrade fails (e.g. table already exists), stamp at head so the app
        # considers the schema up-to-date and try create_all for missing bits.
        try:
            from alembic.config import Config as Cfg2
            from alembic import command as acmd2

            acfg2 = Cfg2("backend/alembic.ini")
            acmd2.stamp(acfg2, "head")
            logger.info("Post-restore: stamped alembic_version to head")
        except Exception as stamp_exc:
            migration_note = f" Warning: schema migration had issues ({exc}), some features may need a restart."
            logger.warning("Post-restore stamp also failed: %s", stamp_exc)

    # 3) Re-create tables that may be missing (belt-and-suspenders)
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass

    return RestoreResponse(
        message=f"Database restored successfully ({tables_restored} tables).{migration_note}",
        tables_restored=tables_restored,
    )


# ── Auto-backup management ────────────────────────────────────


@router.get("/backups")
def list_auto_backups():
    """List available auto-backups (created on every startup)."""
    db_path = _get_db_path()
    backup_dir = db_path.parent / "backups"
    if not backup_dir.exists():
        return {"backups": []}
    backups = []
    for f in sorted(backup_dir.glob("auditforge_*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        backups.append({
            "filename": f.name,
            "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return {"backups": backups}


@router.post("/backups/{filename}/restore")
def restore_auto_backup(filename: str, db: Session = Depends(get_db)):
    """Restore from a specific auto-backup file."""
    db_path = _get_db_path()
    backup_dir = db_path.parent / "backups"
    backup_path = backup_dir / filename

    if not backup_path.exists() or ".." in filename:
        raise HTTPException(status_code=404, detail="Backup not found")
    if not backup_path.name.startswith("auditforge_") or not backup_path.name.endswith(".db"):
        raise HTTPException(status_code=400, detail="Invalid backup filename")

    content = backup_path.read_bytes()
    if not content[:16].startswith(b"SQLite format 3\x00"):
        raise HTTPException(status_code=400, detail="Backup is not a valid SQLite database")

    # Close ALL connections before replacing the file
    db.close()
    engine.dispose()

    try:
        safety = db_path.with_suffix(".db.pre_restore")
        shutil.copy2(str(db_path), str(safety))

        # Remove WAL/SHM files
        for suffix in ("-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                p.unlink(missing_ok=True)

        db_path.write_bytes(content)
        logger.info("Restored from auto-backup: %s (%.1f MB)", filename, len(content) / 1024 / 1024)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Restore failed: {exc}")

    # Run migrations to bring schema up to date
    migration_note = ""
    try:
        from alembic.config import Config
        from alembic import command as alembic_cmd

        alembic_cfg = Config("backend/alembic.ini")
        alembic_cmd.upgrade(alembic_cfg, "head")
    except Exception as exc:
        logger.warning("Post-restore migration issue: %s — stamping head", exc)
        try:
            from alembic.config import Config as Cfg2
            from alembic import command as acmd2

            acfg2 = Cfg2("backend/alembic.ini")
            acmd2.stamp(acfg2, "head")
        except Exception as stamp_exc:
            migration_note = f" (migration warning: {exc})"
            logger.warning("Post-restore stamp failed: %s", stamp_exc)

    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass

    return {
        "message": f"Restored from {filename}.{migration_note}",
        "size_mb": round(len(content) / 1024 / 1024, 2),
    }


# ── Single-key setting (MUST be LAST — catches /{key} patterns) ─────


@router.get("/{key}", response_model=SingleSettingResponse)
def get_setting(key: str, db: Session = Depends(get_db)) -> dict:
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    return {"data": {row.key: row.value}, "message": "success"}
