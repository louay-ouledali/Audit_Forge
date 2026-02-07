from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.core.script_generator import generate_script_package, preview_script_rules
from backend.database import get_db
from backend.models.benchmark import Benchmark
from backend.schemas.scan import (
    GenerateScriptRequest,
    ScriptPreviewResponse,
    ScriptPreviewRule,
)

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("/generate-script")
def generate_script(payload: GenerateScriptRequest, db: Session = Depends(get_db)):
    """Generate an audit script package (ZIP download)."""

    benchmark = db.query(Benchmark).filter(Benchmark.id == payload.benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    filter_kwargs = {
        "selected_rule_ids": payload.selected_rule_ids,
        "category_filter": payload.category_filter,
        "severity_filter": payload.severity_filter,
        "profile_filter": payload.profile_filter,
        "preset_id": payload.preset_id,
    }

    try:
        zip_bytes, zip_filename = generate_script_package(
            db,
            benchmark_id=payload.benchmark_id,
            **filter_kwargs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


@router.post("/generate-script/preview", response_model=ScriptPreviewResponse)
def preview_script(payload: GenerateScriptRequest, db: Session = Depends(get_db)):
    """Preview which rules would be included in the generated script."""

    benchmark = db.query(Benchmark).filter(Benchmark.id == payload.benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    filter_kwargs = {
        "selected_rule_ids": payload.selected_rule_ids,
        "category_filter": payload.category_filter,
        "severity_filter": payload.severity_filter,
        "profile_filter": payload.profile_filter,
        "preset_id": payload.preset_id,
    }

    rules = preview_script_rules(db, benchmark_id=payload.benchmark_id, **filter_kwargs)

    return ScriptPreviewResponse(
        total_rules=len(rules),
        rules=[ScriptPreviewRule(**r) for r in rules],
    )
