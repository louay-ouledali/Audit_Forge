from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request
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
from backend.api.targets import router as targets_router
from backend.config import settings
from backend.database import init_db

logger = logging.getLogger("auditforge")

app = FastAPI(
    title="AditForge API",
    version="0.1.0",
    description="Automated Configuration Review Platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router, prefix="/api")
app.include_router(clients_router, prefix="/api")
app.include_router(missions_router, prefix="/api")
app.include_router(targets_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(benchmarks_router, prefix="/api")
app.include_router(rules_router, prefix="/api")
app.include_router(scans_router, prefix="/api")
app.include_router(findings_router, prefix="/api")
app.include_router(llm_router, prefix="/api")
app.include_router(reports_router, prefix="/api")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception: %s\n%s", exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
