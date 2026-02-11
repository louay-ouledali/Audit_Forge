"""API endpoints for report generation."""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.core.report_generator import (
    aggregate_report_data,
    generate_ai_summary,
    generate_csv_report,
    generate_excel_report,
    generate_html_report,
    generate_pdf_report,
)
from backend.database import get_db
from backend.schemas.report import AISummaryRequest, AISummaryResponse, ReportGenerateRequest

logger = logging.getLogger("auditforge.api.reports")

router = APIRouter(prefix="/reports", tags=["reports"])

VALID_SCOPES = {"scan", "target", "mission", "custom"}
VALID_FORMATS = {"pdf", "excel", "csv", "html"}


@router.post("/generate")
def generate_report(payload: ReportGenerateRequest, db: Session = Depends(get_db)):
    """Generate a report file based on scope and format."""
    if payload.scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"Invalid scope. Must be one of: {', '.join(VALID_SCOPES)}")
    if payload.format not in VALID_FORMATS:
        raise HTTPException(status_code=400, detail=f"Invalid format. Must be one of: {', '.join(VALID_FORMATS)}")
    if payload.scope != "custom" and payload.scope_id is None:
        raise HTTPException(status_code=400, detail="scope_id is required for non-custom scopes")
    if payload.scope == "custom" and not payload.scan_ids:
        raise HTTPException(status_code=400, detail="scan_ids is required for custom scope")

    data = aggregate_report_data(payload.scope, payload.scope_id, payload.scan_ids, db)

    if not data["scans"]:
        raise HTTPException(status_code=404, detail="No scans found for the given scope")

    if payload.title:
        data["title"] = payload.title

    if payload.include_ai_summary:
        import asyncio
        data["ai_summary"] = asyncio.run(generate_ai_summary(data))

    if payload.format == "pdf":
        try:
            content = generate_pdf_report(data, payload.include_passed_rules, db)
        except Exception:
            logger.exception("PDF generation failed")
            raise HTTPException(status_code=500, detail="PDF generation failed")
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=report.pdf"},
        )

    if payload.format == "excel":
        content = generate_excel_report(data, payload.include_passed_rules)
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=report.xlsx"},
        )

    if payload.format == "csv":
        content = generate_csv_report(data)
        return StreamingResponse(
            io.StringIO(content),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=report.csv"},
        )

    # html
    content = generate_html_report(data, payload.include_passed_rules)
    return StreamingResponse(
        io.StringIO(content),
        media_type="text/html",
        headers={"Content-Disposition": "attachment; filename=report.html"},
    )


@router.post("/ai-summary", response_model=AISummaryResponse)
async def generate_ai_summary_endpoint(payload: AISummaryRequest, db: Session = Depends(get_db)):
    """Generate AI executive summary only (preview)."""
    if payload.scope not in ("scan", "target", "mission"):
        raise HTTPException(status_code=400, detail="Scope must be scan, target, or mission")

    data = aggregate_report_data(payload.scope, payload.scope_id, None, db)

    if not data["scans"]:
        raise HTTPException(status_code=404, detail="No scans found for the given scope")

    summary_text = await generate_ai_summary(data)
    return AISummaryResponse(summary=summary_text)
