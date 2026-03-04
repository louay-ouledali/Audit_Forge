"""API endpoints for saved reports — CRUD, generate, download."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.saved_report import SavedReport
from backend.schemas.saved_report import (
    SavedReportCreate,
    SavedReportDetailEnvelope,
    SavedReportListResponse,
    SavedReportResponse,
    SavedReportUpdate,
)

router = APIRouter(prefix="/saved-reports", tags=["saved-reports"])


@router.get("", response_model=SavedReportListResponse)
def list_saved_reports(
    mission_id: int | None = None,
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(SavedReport)
    if mission_id is not None:
        query = query.filter(SavedReport.mission_id == mission_id)
    reports = query.order_by(SavedReport.created_at.desc()).all()
    result = [SavedReportResponse.model_validate(r) for r in reports]
    return {"data": result, "total": len(result)}


@router.post("", response_model=SavedReportDetailEnvelope, status_code=201)
def create_saved_report(payload: SavedReportCreate, db: Session = Depends(get_db)) -> dict:
    report = SavedReport(**payload.model_dump())
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"data": SavedReportResponse.model_validate(report), "message": "Saved report created"}


@router.get("/{report_id}", response_model=SavedReportDetailEnvelope)
def get_saved_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    report = db.query(SavedReport).filter(SavedReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Saved report not found")
    return {"data": SavedReportResponse.model_validate(report), "message": "success"}


@router.put("/{report_id}", response_model=SavedReportDetailEnvelope)
def update_saved_report(
    report_id: int, payload: SavedReportUpdate, db: Session = Depends(get_db)
) -> dict:
    report = db.query(SavedReport).filter(SavedReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Saved report not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(report, field, value)
    report.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(report)
    return {"data": SavedReportResponse.model_validate(report), "message": "Saved report updated"}


@router.delete("/{report_id}")
def delete_saved_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    report = db.query(SavedReport).filter(SavedReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Saved report not found")
    db.delete(report)
    db.commit()
    return {"data": None, "message": "Saved report deleted"}


@router.post("/{report_id}/generate")
def generate_saved_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    """Generate the actual report file (HTML/PDF) from saved config."""
    report = db.query(SavedReport).filter(SavedReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Saved report not found")

    # Parse config
    config = json.loads(report.config_json) if report.config_json else {}
    scan_ids = json.loads(report.scan_ids_json) if report.scan_ids_json else None

    scope = report.scope or config.get("scope", "custom")
    scope_id = report.scope_id or config.get("scope_id")

    try:
        from backend.core.report_generator import aggregate_report_data, generate_html_report, generate_pdf_report

        data = aggregate_report_data(
            scope=scope,
            scope_id=scope_id,
            scan_ids=scan_ids,
            db=db,
            excluded_rule_ids=config.get("excluded_rule_ids"),
        )

        include_passed = config.get("include_passed_rules", True)
        if report.format == "pdf":
            blob = generate_pdf_report(data, include_passed, db)
        else:
            blob = generate_html_report(data, include_passed).encode("utf-8")

        report.generated_blob = blob
        report.file_size_kb = round(len(blob) / 1024, 2)
        report.status = "generated"
        report.generated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(report)

        return {
            "data": SavedReportResponse.model_validate(report),
            "message": "Report generated successfully",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")


@router.get("/{report_id}/download")
def download_saved_report(report_id: int, db: Session = Depends(get_db)):
    """Download the generated report blob."""
    report = db.query(SavedReport).filter(SavedReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Saved report not found")
    if not report.generated_blob:
        raise HTTPException(status_code=404, detail="Report not yet generated")

    media_type = "application/pdf" if report.format == "pdf" else "text/html"
    ext = "pdf" if report.format == "pdf" else "html"
    filename = f"{report.name.replace(' ', '_')}.{ext}"

    return Response(
        content=report.generated_blob,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
