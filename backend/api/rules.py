from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.rule_tag import RuleTag
from backend.schemas.rule import (
    RuleCommandEnvelope,
    RuleCommandResponse,
    RuleCommandUpdate,
    RuleDetailEnvelope,
    RuleResponse,
    RuleTagCreate,
    RuleTagEnvelope,
    RuleTagResponse,
    RuleUpdate,
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


# ── Command Management ──

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
    db.commit()
    db.refresh(cmd)
    return {"data": RuleCommandResponse.model_validate(cmd), "message": "Command updated"}
