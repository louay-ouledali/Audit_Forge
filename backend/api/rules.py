from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand  # UNUSED — safe to remove
from backend.models.rule_tag import RuleTag
from backend.models.verification_report import VerificationReport
from backend.schemas.rule import (
    CommandHistoryEntry,
    CommandHistoryResponse,
    FlagCommandRequest,
    ProtectCommandRequest,
    RegenerateCommandRequest,
    RuleCommandEnvelope,
    RuleCommandResponse,
    RuleCommandUpdate,
    RuleDetailEnvelope,
    RuleResponse,
    RuleTagCreate,
    RuleTagEnvelope,
    RuleTagResponse,
    RuleUpdate,
    UnlockCommandRequest,
    VerificationReportResponse,
    VerificationResultsResponse,
)

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("/{rule_id}", response_model=RuleDetailEnvelope)
def get_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    resp = RuleResponse.model_validate(rule)
    resp.tags = [RuleTagResponse.model_validate(t) for t in rule.tags]
    return {"data": resp, "message": "success"}


@router.put("/{rule_id}", response_model=RuleDetailEnvelope)
def update_rule(rule_id: int, payload: RuleUpdate, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    resp = RuleResponse.model_validate(rule)
    resp.tags = [RuleTagResponse.model_validate(t) for t in rule.tags]
    return {"data": resp, "message": "Rule updated"}


@router.get("/{rule_id}/tags", response_model=RuleTagEnvelope)
def get_rule_tags(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"data": [RuleTagResponse.model_validate(t) for t in rule.tags], "message": "success"}


@router.post("/{rule_id}/tags", response_model=RuleTagEnvelope, status_code=201)
def add_rule_tag(rule_id: int, payload: RuleTagCreate, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    # Check for duplicate
    existing = db.query(RuleTag).filter(RuleTag.rule_id == rule_id, RuleTag.tag_id == payload.tag_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Tag already exists on this rule")
    tag = RuleTag(rule_id=rule_id, tag_id=payload.tag_id, source=payload.source)
    db.add(tag)
    db.commit()
    return {"data": [RuleTagResponse.model_validate(t) for t in rule.tags], "message": "Tag added"}


@router.delete("/{rule_id}/tags/{tag_id}")
def remove_rule_tag(rule_id: int, tag_id: int, db: Session = Depends(get_db)):
    tag = db.query(RuleTag).filter(RuleTag.id == tag_id, RuleTag.rule_id == rule_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.delete(tag)
    db.commit()
    return {"data": None, "message": "Tag removed"}


# Command Management

@router.get("/{rule_id}/command", response_model=RuleCommandEnvelope)
def get_rule_command(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    cmd = rule.commands
    return {"data": RuleCommandResponse.model_validate(cmd) if cmd else None, "message": "success"}


@router.put("/{rule_id}/command", response_model=RuleCommandEnvelope)
def update_rule_command(rule_id: int, payload: RuleCommandUpdate, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    cmd = rule.commands
    if not cmd:
        raise HTTPException(status_code=404, detail="No command exists for this rule")
    if cmd.is_protected:
        raise HTTPException(status_code=400, detail="Command is protected and cannot be edited")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cmd, field, value)
    cmd.source = "auditor_manual"
    cmd.updated_at = datetime.now(timezone.utc)
    cmd.status = "pending_review"
    # Sync edits to the command cache so future benchmarks benefit
    if cmd.audit_command and rule.benchmark_id:
        try:
            from backend.core.command_cache_manager import update_cache_entry
            update_cache_entry(db, cmd, rule)
        except Exception:
            pass  # Cache update is best-effort
    db.commit()
    db.refresh(cmd)
    return {"data": RuleCommandResponse.model_validate(cmd), "message": "Command updated"}


# Command Flagging

@router.post("/{rule_id}/command/flag", response_model=RuleCommandEnvelope)
def flag_command(rule_id: int, payload: FlagCommandRequest, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    cmd = rule.commands
    if not cmd:
        raise HTTPException(status_code=404, detail="No command exists for this rule")
    if cmd.is_protected:
        raise HTTPException(status_code=400, detail="Command is protected and cannot be flagged")

    now = datetime.now(timezone.utc)
    cmd.status = "flagged"
    cmd.flagged_at = now
    cmd.flag_reason = payload.reason
    cmd.flag_error_output = payload.error_output
    cmd.updated_at = now
    db.commit()
    db.refresh(cmd)
    return {"data": RuleCommandResponse.model_validate(cmd), "message": "Command flagged"}


# Command Regeneration

@router.post("/{rule_id}/command/regenerate", response_model=RuleCommandEnvelope)
async def regenerate_command(
    rule_id: int,
    payload: RegenerateCommandRequest | None = None,
    db: Session = Depends(get_db),
):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    cmd = rule.commands
    if not cmd:
        raise HTTPException(status_code=404, detail="No command exists for this rule")
    if cmd.is_protected:
        raise HTTPException(status_code=400, detail="Command is protected and cannot be regenerated")
    if not cmd.flag_reason:
        raise HTTPException(status_code=400, detail="Command must be flagged before regeneration")

    benchmark = rule.benchmark
    if not benchmark:
        raise HTTPException(status_code=400, detail="Rule has no associated benchmark")

    # Save current command to history
    history: list[dict] = []
    if cmd.previous_commands:
        try:
            history = json.loads(cmd.previous_commands)
        except (json.JSONDecodeError, TypeError):
            history = []

    history.append({
        "audit_command": cmd.audit_command,
        "expected_output_regex": cmd.expected_output_regex,
        "flag_reason": cmd.flag_reason,
        "source": cmd.source,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Call AI for regeneration
    from backend.ai.benchmark_ai import regenerate_command as ai_regenerate
    try:
        result = await ai_regenerate(
            section_number=rule.section_number,
            title=rule.title,
            platform=benchmark.platform,
            platform_family=benchmark.platform_family,
            assessment_type=rule.assessment_type,
            audit_description_raw=rule.audit_description_raw,
            remediation_description_raw=rule.remediation_description_raw,
            current_audit_command=cmd.audit_command,
            current_expected_output_regex=cmd.expected_output_regex,
            flag_reason=cmd.flag_reason,
            flag_error_output=cmd.flag_error_output,
            system_info=payload.system_info if payload else None,
            previous_commands=history,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM regeneration failed: {exc}")

    now = datetime.now(timezone.utc)
    cmd.audit_command = result.get("audit_command", cmd.audit_command)
    cmd.expected_output_regex = result.get("expected_output_regex", cmd.expected_output_regex)
    cmd.expected_output_description = result.get("expected_output_description", cmd.expected_output_description)
    cmd.remediation_command = result.get("remediation_command", cmd.remediation_command)
    cmd.remediation_description = result.get("remediation_description", cmd.remediation_description)
    cmd.source = "llm_regenerated"
    cmd.status = "generated"
    cmd.flag_reason = None
    cmd.flag_error_output = None
    cmd.flagged_at = None
    cmd.regeneration_count = (cmd.regeneration_count or 0) + 1
    cmd.last_regenerated_at = now
    cmd.previous_commands = json.dumps(history)
    cmd.updated_at = now
    db.commit()
    db.refresh(cmd)
    return {"data": RuleCommandResponse.model_validate(cmd), "message": "Command regenerated"}


# Command Protection

@router.post("/{rule_id}/command/protect", response_model=RuleCommandEnvelope)
def protect_command(rule_id: int, payload: ProtectCommandRequest | None = None, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    cmd = rule.commands
    if not cmd:
        raise HTTPException(status_code=404, detail="No command exists for this rule")
    if cmd.is_protected:
        raise HTTPException(status_code=400, detail="Command is already protected")
    if cmd.status not in ("verified", "generated"):
        raise HTTPException(status_code=400, detail="Only verified or generated commands can be protected")

    now = datetime.now(timezone.utc)
    cmd.is_protected = True
    cmd.protected_at = now
    cmd.protection_reason = payload.reason if payload else "Manually protected by auditor"
    cmd.updated_at = now
    db.commit()
    db.refresh(cmd)
    return {"data": RuleCommandResponse.model_validate(cmd), "message": "Command protected"}


@router.post("/{rule_id}/command/unlock", response_model=RuleCommandEnvelope)
def unlock_command(rule_id: int, payload: UnlockCommandRequest, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    cmd = rule.commands
    if not cmd:
        raise HTTPException(status_code=404, detail="No command exists for this rule")
    if not cmd.is_protected:
        raise HTTPException(status_code=400, detail="Command is not protected")

    now = datetime.now(timezone.utc)
    cmd.is_protected = False
    cmd.protection_reason = f"Unlocked: {payload.reason}"
    cmd.updated_at = now
    db.commit()
    db.refresh(cmd)
    return {"data": RuleCommandResponse.model_validate(cmd), "message": "Command unlocked"}


# Command History

@router.get("/{rule_id}/command/history", response_model=CommandHistoryResponse)
def get_command_history(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    cmd = rule.commands
    if not cmd:
        return {"data": [], "total": 0, "message": "No command exists"}

    history: list[dict] = []
    if cmd.previous_commands:
        try:
            history = json.loads(cmd.previous_commands)
        except (json.JSONDecodeError, TypeError):
            history = []

    entries = [
        CommandHistoryEntry(
            audit_command=h.get("audit_command"),
            expected_output_regex=h.get("expected_output_regex"),
            flag_reason=h.get("flag_reason"),
            source=h.get("source"),
            timestamp=h.get("timestamp"),
        )
        for h in history
    ]
    return {"data": entries, "total": len(entries), "message": "success"}


# Single Command Verify

@router.post("/{rule_id}/command/verify", response_model=RuleCommandEnvelope)
def verify_single_rule_command(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    cmd = rule.commands
    if not cmd:
        raise HTTPException(status_code=404, detail="No command exists for this rule")
    if cmd.is_protected:
        raise HTTPException(status_code=400, detail="Command is protected — skip verification")

    benchmark = rule.benchmark
    platform_family = benchmark.platform_family if benchmark else "linux"

    from backend.core.verification_engine import verify_command_full
    result = verify_command_full(cmd, platform_family, db)

    now = datetime.now(timezone.utc)
    if result["passed"]:
        cmd.status = "verified"
        cmd.verified_at = now
        cmd.verification_notes = "Passed all checks"
    else:
        cmd.status = "flagged"
        cmd.flagged_at = now
        issues = []
        for level in ("syntax", "safety", "cross_reference", "regex"):
            check = result[level]
            if check["result"] == "fail":
                issues.append(check["message"])
        cmd.flag_reason = "; ".join(issues)
        cmd.verification_notes = json.dumps(result, default=str)

    db.commit()
    db.refresh(cmd)
    return {"data": RuleCommandResponse.model_validate(cmd), "message": "Verification complete"}


# Verification Reports for a Rule Command

@router.get("/{rule_id}/command/verification-reports", response_model=VerificationResultsResponse)
def get_command_verification_reports(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    cmd = rule.commands
    if not cmd:
        return {"data": [], "total": 0, "message": "No command exists"}

    reports = (
        db.query(VerificationReport)
        .filter(VerificationReport.rule_command_id == cmd.id)
        .order_by(VerificationReport.run_at.desc())
        .all()
    )
    return {
        "data": [VerificationReportResponse.model_validate(r) for r in reports],
        "total": len(reports),
        "message": "success",
    }
