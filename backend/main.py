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
from backend.api.configs import router as configs_router
from backend.api.trail import router as trail_router
from backend.api.schedules import router as schedules_router
from backend.api.notifications import router as notifications_router
from backend.api.resolve import router as resolve_router
from backend.api.topology import router as topology_router
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
    # Auto-backup DB before ANY changes (prevents data loss)
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

    # C6: Refuse default dev secret in production
    if (settings.SECRET_KEY == "dev-secret-key-change-in-production"
            and settings.APP_ENV != "development"):
        logger.critical(
            "FATAL: SECRET_KEY is still the default dev value and APP_ENV=%s. "
            "Set a strong SECRET_KEY before deploying to production.",
            settings.APP_ENV,
        )
        raise SystemExit(1)

    # Auto-run Alembic migrations so new columns are always present
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command
        from backend.frozen_paths import ALEMBIC_INI

        alembic_cfg = AlembicConfig(str(ALEMBIC_INI))
        alembic_command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migrations applied successfully")
    except Exception as exc:
        logger.warning("Alembic auto-migration failed (non-fatal): %s", exc)

    # Ensure default admin user exists
    try:
        from backend.database import SessionLocal as _UserSL
        from backend.models.user import User
        from passlib.hash import bcrypt as _bcrypt
        _udb = _UserSL()
        try:
            if _udb.query(User).count() == 0:
                _udb.add(User(
                    username="admin",
                    password_hash=_bcrypt.hash("auditforge"),
                    full_name="Administrator",
                ))
                _udb.commit()
                logger.info("Default admin user created (admin / auditforge)")
        finally:
            _udb.close()
    except Exception as exc:
        logger.warning("Default user check failed (non-fatal): %s", exc)

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
                s.notes = "Interrupted by backend restart — scan was still running when the server shut down"

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

    # Sync pre-loaded benchmark packs from backend/preloaded/
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

    # Start Connect session expiry background task
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

    # Copilot conversation cleanup background task
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

    # Start Forge Sentinel scheduler background loop
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
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting (login + connect sessions ONLY)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Include routers
# Public routes (no JWT required)
app.include_router(auth_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(connect_router, prefix="/api")         # portal endpoints use enrollment codes
app.include_router(ws_agent_router)                       # WebSocket at /ws/agent/{token}

# Protected routes (require valid JWT)
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
app.include_router(configs_router, prefix="/api", dependencies=_auth)
app.include_router(topology_router, prefix="/api", dependencies=_auth)

# Serve pre-built React frontend (Windows native / no nginx)
from backend.frozen_paths import FRONTEND_DIST, FROZEN, BUNDLE_DIR

logger.info("Frozen=%s, BUNDLE_DIR=%s, FRONTEND_DIST=%s, exists=%s",
            FROZEN, BUNDLE_DIR, FRONTEND_DIST, FRONTEND_DIST.exists())

_spa_index = FRONTEND_DIST / "index.html"
if FRONTEND_DIST.exists() and _spa_index.exists():
    from starlette.staticfiles import StaticFiles
    from starlette.responses import FileResponse, HTMLResponse

    logger.info("SPA serving enabled from %s", FRONTEND_DIST)

    # Cache index.html content for fast serving
    _index_html_content = _spa_index.read_text(encoding="utf-8")

    # Explicit root route
    @app.get("/", include_in_schema=False)
    async def serve_root():
        return HTMLResponse(content=_index_html_content)

    # Serve /assets/* as static files
    _assets_dir = FRONTEND_DIST / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="frontend-assets")

    # SPA catch-all for client-side routing (must be after all API routers)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("ws"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # Check for static files first (favicon.ico, etc.)
        static_path = FRONTEND_DIST / full_path
        if static_path.is_file() and ".." not in full_path:
            return FileResponse(str(static_path))
        return HTMLResponse(content=_index_html_content)
else:
    logger.warning("Frontend dist not found at %s — SPA disabled", FRONTEND_DIST)


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
        content={"detail": "Internal server error"},
    )
