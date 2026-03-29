from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.benchmark import Benchmark
from backend.models.client import Client
from backend.models.mission import Mission
from backend.models.rule import Rule
from backend.models.scan import Scan

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    return {"status": "ok", "database": db_status}


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)) -> dict:
    """Return aggregate counts for the dashboard."""
    clients = db.query(func.count(Client.id)).scalar() or 0
    missions = db.query(func.count(Mission.id)).filter(Mission.status != "completed").scalar() or 0
    benchmarks = db.query(func.count(Benchmark.id)).scalar() or 0
    scans = db.query(func.count(Scan.id)).scalar() or 0
    total_rules = db.query(func.count(Rule.id)).scalar() or 0

    return {
        "clients": clients,
        "active_missions": missions,
        "benchmarks": benchmarks,
        "scans": scans,
        "total_rules": total_rules,
    }
