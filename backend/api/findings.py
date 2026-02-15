"""API endpoints for finding browsing, update, and AI advice."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.finding import Finding
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.scan import Scan
from backend.models.benchmark import Benchmark
from backend.schemas.finding import (
    FindingAIAdviceResponse,
    FindingResponse,
    FindingUpdateRequest,
)

router = APIRouter(prefix="/findings", tags=["findings"])

VALID_OVERRIDES = {"confirmed", "false_positive", "accepted_risk", ""}


def _finding_to_response(finding: Finding, db: Session) -> dict:
    """Convert a Finding ORM object to a response dict with joined rule info."""
    rule = db.query(Rule).filter(Rule.id == finding.rule_id).first()
    return {
        "id": finding.id,
        "scan_id": finding.scan_id,
        "rule_id": finding.rule_id,
        "status": finding.status,
        "actual_output": finding.actual_output,
        "expected_output": finding.expected_output,
        "severity": finding.severity,
        "ai_advice": finding.ai_advice,
        "ai_advice_generated_at": finding.ai_advice_generated_at,
        "auditor_notes": finding.auditor_notes,
        "auditor_override": finding.auditor_override,
        "created_at": finding.created_at,
        "section_number": rule.section_number if rule else None,
        "rule_title": rule.title if rule else None,
    }


@router.get("/{finding_id}", response_model=FindingResponse)
def get_finding(finding_id: int, db: Session = Depends(get_db)):
    """Get a single finding with rule details."""
    finding = db.query(Finding).filter(Finding.id == finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return _finding_to_response(finding, db)


@router.put("/{finding_id}", response_model=FindingResponse)
def update_finding(
    finding_id: int,
    payload: FindingUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update auditor notes and/or override on a finding."""
    finding = db.query(Finding).filter(Finding.id == finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    if payload.auditor_notes is not None:
        finding.auditor_notes = payload.auditor_notes
    if payload.auditor_override is not None:
        valid_overrides = VALID_OVERRIDES
        if payload.auditor_override not in valid_overrides:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid override. Must be one of: {', '.join(valid_overrides)}",
            )
        finding.auditor_override = payload.auditor_override or None

    db.commit()
    db.refresh(finding)
    return _finding_to_response(finding, db)


@router.post("/{finding_id}/ai-advice", response_model=FindingAIAdviceResponse)
async def generate_ai_advice(finding_id: int, db: Session = Depends(get_db)):
    """Generate AI remediation advice for a finding (on-demand LLM call).

    If advice was already generated, return the cached version.
    """
    finding = db.query(Finding).filter(Finding.id == finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Return cached advice if available
    if finding.ai_advice and finding.ai_advice_generated_at:
        return FindingAIAdviceResponse(
            advice=finding.ai_advice,
            generated_at=finding.ai_advice_generated_at,
        )

    # Build the prompt
    rule = db.query(Rule).filter(Rule.id == finding.rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Associated rule not found")

    cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule.id).first()
    scan = db.query(Scan).filter(Scan.id == finding.scan_id).first()

    platform = "Unknown"
    if scan:
        benchmark = db.query(Benchmark).filter(Benchmark.id == scan.benchmark_id).first()
        if benchmark:
            platform = benchmark.platform

    prompt = f"""You are a cybersecurity remediation advisor.

A configuration audit found the following misconfiguration:

Rule: {rule.section_number} — {rule.title}
Severity: {finding.severity or 'medium'}
Platform: {platform}
Description: {rule.description or 'N/A'}

Expected (compliant) state:
{cmd.expected_output_description if cmd else 'N/A'}

Actual (non-compliant) output:
{finding.actual_output or 'N/A'}

CIS Remediation Guidance:
{rule.remediation_description_raw or 'N/A'}

Provide:
1. A clear explanation of the security risk
2. Step-by-step remediation instructions specific to this system
3. The exact command(s) to fix this (advisory only — the auditor will decide whether to apply)
4. Any potential impact or side effects of the fix
5. How to verify the fix was applied correctly

Keep the response practical and concise."""

    try:
        from backend.ai.llm_manager import llm_manager
        advice = await llm_manager.invoke(prompt, system_prompt="You are a cybersecurity remediation advisor.", task="reports")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    now = datetime.now(timezone.utc)
    finding.ai_advice = advice
    finding.ai_advice_generated_at = now
    db.commit()

    return FindingAIAdviceResponse(advice=advice, generated_at=now)
