"""API endpoints for post-mission AI analysis (Module 12)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.ai.llm_manager import llm_manager
from backend.core.analysis_engine import (
    get_comparable_missions,
    run_category_analysis,
    run_cross_mission_analysis,
    run_cross_target_analysis,
)
from backend.database import get_db
from backend.models.client import Client
from backend.models.mission import Mission
from backend.models.mission_analysis import MissionAnalysis
from backend.schemas.analysis import (
    AnalysisDetailEnvelope,
    AnalysisListResponse,
    AnalysisRequest,
    AnalysisResponse,
    ComparableMissionListResponse,
)

logger = logging.getLogger("auditforge.api.analyses")

router = APIRouter(tags=["analyses"])

VALID_ANALYSIS_TYPES = {"cross_target", "cross_mission", "category_analysis"}


def _to_response(analysis: MissionAnalysis) -> AnalysisResponse:
    """Convert a MissionAnalysis ORM object to an AnalysisResponse."""
    try:
        result = json.loads(analysis.result_json)
    except (json.JSONDecodeError, TypeError):
        result = {}
    return AnalysisResponse(
        id=analysis.id,
        mission_id=analysis.mission_id,
        analysis_type=analysis.analysis_type,
        compared_mission_id=analysis.compared_mission_id,
        result=result,
        llm_model_used=analysis.llm_model_used,
        generated_at=analysis.generated_at,
    )


@router.post("/missions/{mission_id}/analyze", response_model=AnalysisDetailEnvelope)
async def run_analysis(mission_id: int, payload: AnalysisRequest, db: Session = Depends(get_db)):
    """Run an AI-powered post-mission analysis."""
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    if payload.analysis_type not in VALID_ANALYSIS_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid analysis_type. Must be one of: {', '.join(VALID_ANALYSIS_TYPES)}",
        )

    if payload.analysis_type == "cross_mission" and not payload.compare_mission_id:
        raise HTTPException(status_code=400, detail="compare_mission_id is required for cross_mission analysis")

    if payload.analysis_type == "cross_mission" and payload.compare_mission_id:
        compare = db.query(Mission).filter(Mission.id == payload.compare_mission_id).first()
        if not compare:
            raise HTTPException(status_code=404, detail="Comparison mission not found")
        if compare.client_id != mission.client_id:
            raise HTTPException(status_code=400, detail="Cannot compare missions from different clients")

    try:
        if payload.analysis_type == "cross_target":
            result = await run_cross_target_analysis(mission_id, db)
        elif payload.analysis_type == "category_analysis":
            result = await run_category_analysis(mission_id, db)
        else:
            result = await run_cross_mission_analysis(mission_id, payload.compare_mission_id, db)  # type: ignore[arg-type]
    except Exception as exc:
        logger.exception("Analysis failed for mission %s", mission_id)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

    # Get the LLM model name
    config = llm_manager.get_current_config()
    model_used = config.get("offline_model") if config["mode"] == "offline" else config.get("online_model")

    analysis = MissionAnalysis(
        mission_id=mission_id,
        analysis_type=payload.analysis_type,
        compared_mission_id=payload.compare_mission_id,
        result_json=json.dumps(result),
        llm_model_used=model_used or "unknown",
        generated_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    return {"data": _to_response(analysis), "message": "Analysis completed"}


@router.get("/missions/{mission_id}/analyses", response_model=AnalysisListResponse)
def list_analyses(mission_id: int, db: Session = Depends(get_db)):
    """List all analyses for a mission."""
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    analyses = (
        db.query(MissionAnalysis)
        .filter(MissionAnalysis.mission_id == mission_id)
        .order_by(MissionAnalysis.generated_at.desc())
        .all()
    )
    data = [_to_response(a) for a in analyses]
    return {"data": data, "total": len(data)}


@router.get("/missions/{mission_id}/analyses/{analysis_id}", response_model=AnalysisDetailEnvelope)
def get_analysis(mission_id: int, analysis_id: int, db: Session = Depends(get_db)):
    """Get a specific analysis result."""
    analysis = (
        db.query(MissionAnalysis)
        .filter(MissionAnalysis.mission_id == mission_id, MissionAnalysis.id == analysis_id)
        .first()
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return {"data": _to_response(analysis), "message": "success"}


@router.delete("/missions/{mission_id}/analyses/{analysis_id}")
def delete_analysis(mission_id: int, analysis_id: int, db: Session = Depends(get_db)):
    """Delete an analysis."""
    analysis = (
        db.query(MissionAnalysis)
        .filter(MissionAnalysis.mission_id == mission_id, MissionAnalysis.id == analysis_id)
        .first()
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    db.delete(analysis)
    db.commit()
    return {"data": None, "message": "Analysis deleted"}


@router.get("/clients/{client_id}/missions/comparable", response_model=ComparableMissionListResponse)
def list_comparable_missions(client_id: int, db: Session = Depends(get_db)):
    """List missions for a client that can be compared (have at least one scan)."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    missions = get_comparable_missions(client_id, db)
    return {"data": missions}
