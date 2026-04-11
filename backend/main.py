from __future__ import annotations

import logging
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.benchmarks import router as benchmarks_router
from backend.api.findings import router as findings_router
from backend.api.clients import router as clients_router
from backend.api.health import router as health_router
from backend.api.llm import router as llm_router
from backend.api.missions import router as missions_router
from backend.api.rules import router as rules_router
from backend.api.scans import router as scans_router
from backend.api.settings import router as settings_router
from backend.api.reports import router as reports_router
from backend.api.saved_reports import router as saved_reports_router
from backend.api.targets import router as targets_router
from backend.api.analyses import router as analyses_router
from backend.api.ad_discovery import router as ad_discovery_router
from backend.api.connect import router as connect_router
from backend.api.copilot import router as copilot_router
from backend.api.auth import router as auth_router
from backend.api.trail import router as trail_router
from backend.api.schedules import router as schedules_router
from backend.api.notifications import router as notifications_router
from backend.api.resolve import router as resolve_router
from backend.api.ws_agent import router as ws_agent_router
from backend.config import settings
from backend.core.exceptions import (
    AuditForgeError,
    BackupError,
    BenchmarkError,
    ConnectionFailedError,
    ConnectionTimeoutError,
    LLMError,
    ScanError,
)
from backend.core.auth import get_current_user
from backend.database import init_db

# Configure logging for auditforge loggers so Phase 2/AI messages are visible
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")
logging.getLogger("auditforge").setLevel(logging.INFO)

logger = logging.getLogger("auditforge")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # ── Auto-backup DB before ANY changes (prevents data loss) ───────────
    try:
        from backend.config import settings as _cfg
        from pathlib import Path
        import shutil

        db_url = _cfg.resolved_database_url
        if db_url.startswith("sqlite:///"):
            db_path = Path(db_url.replace("sqlite:///", ""))
            if db_path.exists() and db_path.stat().st_size > 0:
                backup_dir = db_path.parent / "backups"
                backup_dir.mkdir(exist_ok=True)
                from datetime import datetime as _dt
                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"auditforge_{ts}.db"
                shutil.copy2(str(db_path), str(backup_path))
                logger.info("Auto-backup created: %s (%.1f MB)", backup_path.name, db_path.stat().st_size / 1024 / 1024)

                # Keep only last 5 backups to avoid disk bloat
                backups = sorted(backup_dir.glob("auditforge_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
                for old in backups[5:]:
                    old.unlink()
                    logger.debug("Removed old backup: %s", old.name)
    except Exception as exc:
        logger.warning("Auto-backup failed (non-fatal): %s", exc)

    init_db()

    # ── Auto-run Alembic migrations so new columns are always present ────
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command
        import os

        alembic_ini = os.path.join(os.path.dirname(__file__), "alembic.ini")
        alembic_cfg = AlembicConfig(alembic_ini)
        alembic_command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migrations applied successfully")
    except Exception as exc:
        logger.warning("Alembic auto-migration failed (non-fatal): %s", exc)

    # Reset stale "processing" phase2 statuses left by crashed containers
    # (must run AFTER migrations so all columns exist)
    try:
        from backend.database import SessionLocal
        from backend.models.benchmark import Benchmark
        from backend.models.scan import Scan
        db = SessionLocal()
        try:
            stale = db.query(Benchmark).filter(Benchmark.phase2_status == "processing").all()
            for b in stale:
                logger.info("Resetting stale phase2_status for benchmark %d", b.id)
                b.phase2_status = "pending"

            # Also reset orphaned scans stuck in "running" from a previous crash
            orphaned = db.query(Scan).filter(Scan.status == "running").all()
            for s in orphaned:
                logger.info("Resetting orphaned running scan %d to failed", s.id)
                s.status = "failed"
                s.error_message = "Interrupted by backend restart"

            # Reset orphaned Sentinel runs stuck in "running"
            from backend.models.sentinel_run import SentinelRun
            from datetime import datetime, timezone
            orphaned_runs = db.query(SentinelRun).filter(SentinelRun.status == "running").all()
            for r in orphaned_runs:
                logger.info("Resetting orphaned sentinel run %d to failed", r.id)
                r.status = "failed"
                r.completed_at = datetime.now(timezone.utc)

            if stale or orphaned or orphaned_runs:
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Failed to reset stale statuses: %s", exc)

    # ── Sync pre-loaded benchmark packs from backend/preloaded/ ──────────
    try:
        from backend.core.preloaded_loader import sync_preloaded
        from backend.database import SessionLocal as _SL
        _db = _SL()
        try:
            result = sync_preloaded(_db)
            if result["loaded"] or result["upgraded"]:
                logger.info(
                    "Preloaded sync: %d loaded, %d upgraded, %d skipped, %d errors",
                    result["loaded"], result["upgraded"],
                    result["skipped"], result["errors"],
                )
        finally:
            _db.close()
    except Exception as exc:
        logger.warning("Preloaded benchmark sync failed: %s", exc)

    # ── Start Connect session expiry background task ──────────────────
    async def _session_expiry_loop():
        import asyncio as _aio
        from backend.models.connect_session import ConnectSession as _CS
        from backend.models.connect_agent import ConnectAgent as _CA
        from backend.core import agent_registry as _ar

        while True:
            await _aio.sleep(60)
            try:
                _db = SessionLocal()
                try:
                    now = datetime.now(timezone.utc)
                    # Expire sessions past their deadline
                    active = _db.query(_CS).filter(_CS.status == "active").all()
                    for s in active:
                        exp = s.expires_at
                        if exp and (exp.tzinfo is None and now.replace(tzinfo=None) > exp
                                    or exp.tzinfo and now > exp):
                            s.status = "expired"
                            # Disconnect live agents
                            for live in _ar.get_by_session(s.id):
                                try:
                                    await live.websocket.send_json({
                                        "type": "terminate",
                                        "payload": {"reason": "session_expired"},
                                    })
                                    await live.websocket.close()
                                except Exception:
                                    pass
                            logger.info("Connect session %d auto-expired", s.id)
                    _db.commit()
                finally:
                    _db.close()
            except Exception as exc:
                logger.debug("Session expiry check error (non-fatal): %s", exc)

    # ── Copilot conversation cleanup background task ──────────────
    async def _copilot_conversation_cleanup_loop():
        import asyncio as _aio
        from backend.api.copilot import cleanup_expired_conversations

        while True:
            await _aio.sleep(300)  # Every 5 minutes
            try:
                cleanup_expired_conversations()
            except Exception as exc:
                logger.debug("Copilot conversation cleanup error (non-fatal): %s", exc)

    import asyncio as _asyncio
    from datetime import datetime, timezone
    from backend.database import SessionLocal

    _bg_tasks: list[_asyncio.Task] = []

    async def _supervised(name: str, coro_factory, *args, restart_delay: float = 5.0):
        """Run a coroutine with crash logging and auto-restart."""
        while True:
            try:
                await coro_factory(*args)
            except _asyncio.CancelledError:
                logger.info("Background task '%s' cancelled", name)
                return
            except Exception as exc:
                logger.error("Background task '%s' crashed: %s — restarting in %ds", name, exc, restart_delay)
                await _asyncio.sleep(restart_delay)

    _bg_tasks.append(_asyncio.create_task(_supervised("session_expiry", _session_expiry_loop)))
    _bg_tasks.append(_asyncio.create_task(_supervised("copilot_cleanup", _copilot_conversation_cleanup_loop)))

    # ── Start Forge Sentinel scheduler background loop ─────────────────
    from backend.core.sentinel import sentinel_loop
    _bg_tasks.append(_asyncio.create_task(_supervised("sentinel_loop", sentinel_loop, SessionLocal)))

    yield

    # Shutdown — cancel all background tasks
    for t in _bg_tasks:
        t.cancel()
    await _asyncio.gather(*_bg_tasks, return_exceptions=True)
    logger.info("All background tasks stopped")


app = FastAPI(
    title="AuditForge API",
    version="0.1.0",
    description="Automated Configuration Review Platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
# ── Public routes (no JWT required) ──────────────────────────────────
app.include_router(auth_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(connect_router, prefix="/api")         # portal endpoints use enrollment codes
app.include_router(ws_agent_router)                       # WebSocket at /ws/agent/{token}

# ── Protected routes (require valid JWT) ─────────────────────────────
_auth = [Depends(get_current_user)]
app.include_router(trail_router, prefix="/api", dependencies=_auth)
app.include_router(clients_router, prefix="/api", dependencies=_auth)
app.include_router(missions_router, prefix="/api", dependencies=_auth)
app.include_router(targets_router, prefix="/api", dependencies=_auth)
app.include_router(settings_router, prefix="/api", dependencies=_auth)
app.include_router(benchmarks_router, prefix="/api", dependencies=_auth)
app.include_router(rules_router, prefix="/api", dependencies=_auth)
app.include_router(scans_router, prefix="/api", dependencies=_auth)
app.include_router(findings_router, prefix="/api", dependencies=_auth)
app.include_router(llm_router, prefix="/api", dependencies=_auth)
app.include_router(reports_router, prefix="/api", dependencies=_auth)
app.include_router(saved_reports_router, prefix="/api", dependencies=_auth)
app.include_router(analyses_router, prefix="/api", dependencies=_auth)
app.include_router(ad_discovery_router, prefix="/api", dependencies=_auth)
app.include_router(copilot_router, prefix="/api", dependencies=_auth)
app.include_router(schedules_router, prefix="/api", dependencies=_auth)
app.include_router(notifications_router, prefix="/api", dependencies=_auth)
app.include_router(resolve_router, prefix="/api", dependencies=_auth)


@app.exception_handler(AuditForgeError)
async def auditforge_error_handler(request: Request, exc: AuditForgeError) -> JSONResponse:
    """Handle structured AditForge errors with appropriate status codes."""
    status_map: dict[type, int] = {
        ConnectionFailedError: 502,
        ConnectionTimeoutError: 504,
        LLMError: 503,
        BenchmarkError: 422,
        ScanError: 500,
        BackupError: 500,
    }
    # Walk up the MRO to find the most specific matching status code
    status_code = 500
    for cls in type(exc).__mro__:
        if cls in status_map:
            status_code = status_map[cls]
            break

    logger.error("%s: %s", type(exc).__name__, exc.message)
    payload: dict = {"detail": exc.message, "error_type": type(exc).__name__}
    if exc.detail:
        payload["error_detail"] = exc.detail
    return JSONResponse(status_code=status_code, content=payload)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception: %s\n%s", exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_type": type(exc).__name__},
    )
