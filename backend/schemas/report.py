"""Pydantic schemas for report generation."""
from __future__ import annotations

from pydantic import BaseModel


class RuleGroupInline(BaseModel):
    """Inline rule group for report requests (avoids forward reference issues)."""
    name: str
    rule_ids: list[int]


class ReportGenerateRequest(BaseModel):
    scope: str  # "scan", "target", "mission", "custom"
    scope_id: int | None = None
    scan_ids: list[int] | None = None  # for "custom" scope
    format: str  # "pdf", "excel", "csv", "html"
    include_ai_summary: bool = False
    include_passed_rules: bool = True
    title: str | None = None
    excluded_rule_ids: list[int] | None = None  # exclude specific rules from the report
    groups: list[RuleGroupInline] | None = None
    audience: str = "technical"
    sections: dict[str, bool] | None = None
    group_summaries: dict[str, str] | None = None
    severity_filter: list[str] | None = None


class AISummaryRequest(BaseModel):
    scope: str  # "scan", "target", "mission", "custom"
    scope_id: int | None = None
    scan_ids: list[int] | None = None


class AISummaryResponse(BaseModel):
    summary: str


# ── Report Builder schemas ────────────────────────────────────


class BuilderPreviewRequest(BaseModel):
    """Request for generating a live HTML preview in the Report Builder."""
    scan_ids: list[int]
    excluded_rule_ids: list[int] | None = None
    include_passed_rules: bool = True
    title: str | None = None
    groups: list["RuleGroup"] | None = None
    audience: str = "technical"
    sections: dict[str, bool] | None = None
    group_summaries: dict[str, str] | None = None
    severity_filter: list[str] | None = None


class BuilderFindingsRequest(BaseModel):
    """Fetch findings for selected scans (for rule selection step)."""
    scan_ids: list[int]


# ── Phase 2: Grouping & Audience ──────────────────────────────


class AutoGroupRequest(BaseModel):
    """Request AI/keyword auto-grouping of selected rules."""
    scan_ids: list[int]
    excluded_rule_ids: list[int] | None = None


class RuleGroup(BaseModel):
    """A named group / section of rules."""
    name: str
    rule_ids: list[int]


class GroupSummaryRequest(BaseModel):
    """Request an AI-generated summary for a rule group."""
    group_name: str
    rule_ids: list[int]
    scan_ids: list[int]
    audience: str = "technical"  # executive, technical, compliance


class GroupSummaryResponse(BaseModel):
    summary: str


# BuilderPreviewRequestV2 merged into BuilderPreviewRequest above
