"""Forge Copilot — core engine: intent routing, rule mining, gap analysis."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.ai.copilot_prompts import (
    EXPLAIN_RULE_PROMPT,
    GAP_POLISH_PROMPT,
    RULE_GENERATION_PROMPT,
)
from backend.ai.llm_manager import llm_manager
from backend.ai.prompt_sanitizer import sanitize_field
from backend.core.command_templates import match_template
from backend.core.rule_categorizer import TAG_KEYWORDS, auto_tag_rule
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand

logger = logging.getLogger(__name__)

# Dataclasses

@dataclass
class PendingRule:
    section_number: str
    title: str
    description: str
    severity: str = "medium"
    source_benchmark: str | None = None
    confidence: float = 0.0
    command_data: dict | None = None
    command_source: str | None = None   # template / cache / llm
    category: str | None = None


@dataclass
class Intent:
    name: str
    entities: dict = field(default_factory=dict)
    raw_message: str = ""


# Intent patterns (NLP, zero LLM)

INTENT_PATTERNS: dict[str, list[str]] = {
    "create_benchmark": [
        r"(?:create|build|make|generate|new)\s+(?:a\s+)?(?:\w+\s+)?(?:benchmark|pack|ruleset)",
        r"(?:hardening|security)\s+(?:benchmark|rules?)\s+for\s+(\w+)",
        r"benchmark\s+for\s+(\w+)",
    ],
    "add_rules": [
        r"(?:add|create|generate|include)\s+(?:a\s+)?(?:rules?|checks?|controls?)",
        r"(?:add|include)\s+(?:rules?\s+)?(?:for|about|to check)\s+(.+)",
    ],
    "search_rules": [
        r"(?:find|search|look for|show me|where is)\s+(?:the\s+)?rule",
        r"(?:which|what)\s+rules?\s+(?:checks?|covers?|handles?)",
    ],
    "explain_rule": [
        r"(?:explain|what does|describe|tell me about)\s+(?:rule\s+)?(\d+[\.\d]*)",
        r"what\s+(?:does|is)\s+(?:this|that)\s+rule",
    ],
    "edit_rules": [
        r"(?:change|update|modify|edit|set)\s+(?:the\s+)?(?:severity|title|description)",
        r"(?:mass|bulk)\s+(?:edit|update|change)",
    ],
    "suggest_gaps": [
        r"(?:what(?:'s| is)?\s+missing|gaps?|coverage|suggest)",
        r"(?:am I|are we)\s+missing",
    ],
}


def route_intent(message: str, context: dict) -> Intent:
    """Classify user intent via regex patterns; fall back to LLM."""
    text = message.lower().strip()
    for intent_name, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                entities = {}
                if m.lastindex:
                    entities["extracted"] = m.group(m.lastindex).strip()
                return Intent(name=intent_name, entities=entities, raw_message=message)
    # Fallback: general chat
    return Intent(name="general_chat", entities={}, raw_message=message)


# Rule Mining (Agent 1 — pure DB)

def _jaccard_similarity(text_a: str, text_b: str) -> float:
    words_a = set(re.findall(r"\w+", text_a.lower()))
    words_b = set(re.findall(r"\w+", text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def mine_existing_rules(
    platform_family: str,
    description: str,
    db: Session,
    *,
    exclude_benchmark_id: int | None = None,
    threshold: float = 0.25,
    max_results: int = 60,
) -> list[PendingRule]:
    """Search existing benchmarks for rules applicable to a given platform/description."""
    # Extract keywords for DB-level pre-filtering (P6)
    keywords = [w for w in re.findall(r"\w{3,}", description.lower()) if len(w) >= 3]

    similar_benchmarks = (
        db.query(Benchmark)
        .filter(Benchmark.platform_family == platform_family)
        .all()
    )
    bm_ids = [
        bm.id for bm in similar_benchmarks
        if not (exclude_benchmark_id and bm.id == exclude_benchmark_id)
    ]
    bm_map = {bm.id: bm for bm in similar_benchmarks}

    if not bm_ids:
        return []

    # DB-level keyword pre-filter: only load rules matching at least one keyword
    base_query = db.query(Rule).filter(Rule.benchmark_id.in_(bm_ids))
    if keywords:
        keyword_filters = [Rule.title.ilike(f"%{kw}%") for kw in keywords[:5]]
        from sqlalchemy import or_
        rules = base_query.filter(or_(*keyword_filters)).all()
    else:
        rules = base_query.all()

    candidates: list[tuple[float, Rule, Benchmark]] = []
    for rule in rules:
        bm = bm_map.get(rule.benchmark_id)
        if not bm:
            continue
        score = _jaccard_similarity(description, rule.title)
        if score >= threshold:
            candidates.append((score, rule, bm))

    # Deduplicate by normalized title
    seen_titles: set[str] = set()
    deduped: list[PendingRule] = []
    for score, rule, bm in sorted(candidates, key=lambda x: -x[0]):
        norm = re.sub(r"\s+", " ", rule.title.lower().strip())
        if norm in seen_titles:
            continue
        seen_titles.add(norm)
        deduped.append(
            PendingRule(
                section_number=rule.section_number,
                title=rule.title,
                description=rule.description or "",
                severity=rule.severity or "medium",
                source_benchmark=bm.name if hasattr(bm, "name") else f"Benchmark #{bm.id}",
                confidence=round(min(score + 0.3, 1.0), 2),
                category=None,
            )
        )
        if len(deduped) >= max_results:
            break

    return deduped


# Template Matching (Agent 2 — zero LLM)

def match_templates_for_candidates(
    candidates: list[PendingRule],
    platform_family: str,
) -> list[PendingRule]:
    """Try to generate commands via deterministic templates for each candidate."""
    for c in candidates:
        rule_dict = {
            "section_number": c.section_number,
            "title": c.title,
            "audit_description_raw": c.description,
            "remediation_description_raw": "",
        }
        result = match_template(rule_dict, platform_family)
        if result:
            c.command_source = "template"
            c.command_data = result
            c.confidence = min(c.confidence + 0.15, 1.0)
    return candidates


# Coverage Gap Analysis (Agent 3 — mostly NLP)

EXPECTED_CATEGORIES: dict[str, list[str]] = {
    "linux": [
        "password_policy", "user_accounts", "ssh_configuration", "network_security",
        "filesystem_permissions", "audit_logging", "service_hardening", "encryption_tls",
        "kernel_hardening", "time_synchronization", "patch_updates",
    ],
    "unix": [  # alias for linux — some old benchmarks may use "unix"
        "password_policy", "user_accounts", "ssh_configuration", "network_security",
        "filesystem_permissions", "audit_logging", "service_hardening", "encryption_tls",
        "kernel_hardening", "time_synchronization", "patch_updates",
    ],
    "windows": [
        "password_policy", "user_accounts", "network_security", "audit_logging",
        "service_hardening", "encryption_tls", "access_control", "windows_security",
        "patch_updates",
    ],
    "database": [
        "database_security", "user_accounts", "encryption_tls", "audit_logging",
        "access_control", "network_security", "patch_updates",
    ],
    "network": [
        "network_device", "network_security", "encryption_tls", "audit_logging",
        "access_control", "service_hardening",
    ],
}


def analyze_coverage_gaps(
    platform_family: str,
    current_rules: list[Rule],
) -> list[str]:
    """Identify security categories missing from the current rule set."""
    covered: set[str] = set()
    for rule in current_rules:
        tags = auto_tag_rule(
            title=rule.title,
            description=rule.description or "",
            audit_raw=rule.audit_description_raw or "",
            remediation_raw=rule.remediation_description_raw or "",
            section_number=rule.section_number,
        )
        covered.update(tags)

    expected = set(EXPECTED_CATEGORIES.get(
        platform_family.lower() if platform_family else "linux",
        EXPECTED_CATEGORIES.get("linux", []),
    ))
    return sorted(expected - covered)


# Merger

def merge_and_rank(
    mined: list[PendingRule],
    gaps: list[str],
    *,
    max_rules: int = 50,
) -> tuple[list[PendingRule], list[str]]:
    """Rank mined rules by confidence, return (auto_rules, uncovered_gap_categories)."""
    # Sort by confidence descending
    ranked = sorted(mined, key=lambda r: -r.confidence)[:max_rules]

    # Determine which gaps ARE covered by mined rules
    covered_gaps: set[str] = set()
    for r in ranked:
        if r.category:
            covered_gaps.add(r.category)
        # Also categorize by title
        tags = auto_tag_rule(title=r.title, description=r.description)
        covered_gaps.update(tags)

    remaining_gaps = [g for g in gaps if g not in covered_gaps]
    return ranked, remaining_gaps


# LLM Rule Generation (last resort, ~20% of cases)

async def generate_rules_for_gaps(
    gaps: list[str],
    platform: str,
    platform_family: str,
    next_section_start: int = 100,
) -> list[PendingRule]:
    """Use LLM to generate rules for coverage gaps that DB mining couldn't fill."""
    if not gaps:
        return []

    prompt = RULE_GENERATION_PROMPT.format(
        platform=platform,
        platform_family=platform_family,
        gap_descriptions="\n".join(f"- {g.replace('_', ' ').title()}" for g in gaps),
        next_section=f"{next_section_start}.1.1",
    )
    try:
        result = await llm_manager.invoke_json(prompt, task="copilot")
        if not isinstance(result, list):
            result = result.get("rules", []) if isinstance(result, dict) else []

        pending: list[PendingRule] = []
        for r in result:
            pending.append(PendingRule(
                section_number=str(r.get("section_number", f"{next_section_start}.{len(pending)+1}")),
                title=r.get("title", "Untitled Rule"),
                description=r.get("description", ""),
                severity=r.get("severity", "medium"),
                confidence=0.4,
                command_source="llm",
                category=r.get("category"),
            ))
        return pending
    except Exception:
        logger.exception("LLM rule generation failed for gaps")
        return []


# Explain Rule

async def explain_rule(rule: Rule, db: Session) -> str:
    """Generate a plain-English explanation of a rule."""
    cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule.id).first()
    prompt = EXPLAIN_RULE_PROMPT.format(
        section_number=rule.section_number,
        title=sanitize_field(rule.title or "", max_length=300),
        description=sanitize_field(rule.description or "N/A", max_length=500),
        audit_command=sanitize_field(cmd.audit_command if cmd else "N/A", max_length=500),
        expected_output_description=sanitize_field(cmd.expected_output_description if cmd else "N/A", max_length=500),
    )
    try:
        return await llm_manager.invoke(prompt, task="copilot")
    except Exception:
        return f"Rule **{rule.section_number}**: {rule.title}\n\n{rule.description or 'No description available.'}"


# Full Pipeline Orchestrator

async def run_copilot_pipeline(
    benchmark_id: int,
    description: str,
    platform: str,
    platform_family: str,
    db: Session,
    *,
    max_rules: int = 50,
) -> dict[str, Any]:
    """
    Run the full multi-agent pipeline:
      1. Mine existing rules (DB only)
      2. Match command templates (zero LLM)
      3. Analyze coverage gaps (NLP)
      4. Generate rules for remaining gaps (LLM — last resort)
    Returns a summary with pending rules.
    """
    progress: list[str] = []

    # Agent 1: Mine
    progress.append(f"Mining existing rules across benchmarks for {platform_family}...")
    mined = mine_existing_rules(
        platform_family=platform_family,
        description=description,
        db=db,
        exclude_benchmark_id=benchmark_id,
    )
    progress.append(f"Found {len(mined)} candidate rules from existing benchmarks")

    # Agent 2: Template match
    progress.append("Matching command templates...")
    mined = match_templates_for_candidates(mined, platform_family)
    template_count = sum(1 for r in mined if r.command_source == "template")
    progress.append(f"{template_count} commands generated instantly via templates")

    # Agent 3: Coverage gaps
    current_rules = db.query(Rule).filter(Rule.benchmark_id == benchmark_id).all()
    gaps = analyze_coverage_gaps(platform_family, current_rules)
    progress.append(f"Coverage analysis: {len(gaps)} potentially missing categories")

    # Merge & rank
    ranked, remaining_gaps = merge_and_rank(mined, gaps, max_rules=max_rules)

    # Agent 4: LLM for remaining gaps
    llm_rules: list[PendingRule] = []
    if remaining_gaps:
        progress.append(f"Generating rules with AI for {len(remaining_gaps)} gap areas...")
        try:
            next_section = max((int(r.section_number.split(".")[0]) for r in current_rules if r.section_number), default=0) + 100
        except (ValueError, AttributeError):
            next_section = 100
        llm_rules = await generate_rules_for_gaps(remaining_gaps, platform, platform_family, next_section)
        progress.append(f"AI generated {len(llm_rules)} new rules")

    all_pending = ranked + llm_rules

    return {
        "pending_rules": [
            {
                "section_number": r.section_number,
                "title": r.title,
                "description": r.description,
                "severity": r.severity,
                "confidence": r.confidence,
                "source_benchmark": r.source_benchmark,
                "command_source": r.command_source,
                "command_data": r.command_data,
                "category": r.category,
            }
            for r in all_pending
        ],
        "progress": progress,
        "stats": {
            "mined": len(mined),
            "template_matched": template_count,
            "gaps_found": len(gaps),
            "llm_generated": len(llm_rules),
            "total_pending": len(all_pending),
        },
    }
