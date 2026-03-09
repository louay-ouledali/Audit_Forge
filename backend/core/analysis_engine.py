"""Post-mission AI analysis engine (Module 12)."""
from __future__ import annotations

import json  # UNUSED — safe to remove
import logging
from typing import Any

from sqlalchemy.orm import Session

from backend.ai.llm_manager import llm_manager
from backend.ai.prompts import ANALYSIS_CATEGORY, ANALYSIS_CROSS_MISSION, ANALYSIS_CROSS_TARGET
from backend.models.client import Client
from backend.models.finding import Finding
from backend.models.mission import Mission
from backend.models.rule import Rule
from backend.models.rule_tag import RuleTag
from backend.models.scan import Scan
from backend.models.target import Target

logger = logging.getLogger("auditforge.analysis")


def _gather_mission_data(mission_id: int, db: Session) -> dict[str, Any]:
    """Collect all targets, scans, and findings for a mission."""
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise ValueError(f"Mission {mission_id} not found")

    client = db.query(Client).filter(Client.id == mission.client_id).first()

    # Scans now have direct mission_id; get unique targets from those scans
    scans_for_mission = db.query(Scan).filter(Scan.mission_id == mission_id).all()
    target_ids = {s.target_id for s in scans_for_mission}
    targets = db.query(Target).filter(Target.id.in_(target_ids)).all() if target_ids else []

    result: dict[str, Any] = {
        "mission": mission,
        "client": client,
        "targets": [],
    }

    for target in targets:
        scans = [s for s in scans_for_mission if s.target_id == target.id]
        target_findings: list[dict[str, Any]] = []
        total_pass = 0
        total_fail = 0
        total_checked = 0

        for scan in scans:
            findings = db.query(Finding).filter(Finding.scan_id == scan.id).all()
            for f in findings:
                rule = db.query(Rule).filter(Rule.id == f.rule_id).first()
                target_findings.append({
                    "status": f.status,
                    "severity": f.severity or (rule.severity if rule else "medium"),
                    "section_number": rule.section_number if rule else "",
                    "title": rule.title if rule else "",
                    "actual_output": (f.actual_output or "")[:200],
                })
            total_pass += scan.passed or 0
            total_fail += scan.failed or 0
            total_checked += scan.total_rules_checked or 0

        compliance = round((total_pass / total_checked * 100), 1) if total_checked > 0 else 0.0
        result["targets"].append({
            "hostname": target.hostname or target.ip_address or f"target-{target.id}",
            "target_type": target.target_type,
            "os_details": target.os_details or "",
            "compliance_percentage": compliance,
            "findings": target_findings,
            "total_pass": total_pass,
            "total_fail": total_fail,
        })

    return result


def _build_cross_target_prompt(data: dict[str, Any]) -> str:
    """Build the LLM prompt for cross-target pattern detection."""
    lines: list[str] = []
    for t in data["targets"]:
        lines.append(f"  Target: {t['hostname']} ({t['target_type']}, {t['os_details']})")
        lines.append(f"  Compliance: {t['compliance_percentage']}%")
        lines.append("  Failed Rules:")
        for f in t["findings"]:
            if f["status"] == "FAIL":
                lines.append(f"    - [{f['severity']}] {f['section_number']}: {f['title']}")
                if f["actual_output"]:
                    lines.append(f"      Actual: {f['actual_output']}")
        lines.append("")

    return ANALYSIS_CROSS_TARGET.format(
        mission_name=data["mission"].name,
        client_name=data["client"].name if data["client"] else "Unknown",
        targets_findings="\n".join(lines),
    )


def _build_category_prompt(data: dict[str, Any], db: Session) -> str:
    """Build the LLM prompt for category-level analysis."""
    # Collect category stats across all findings
    category_stats: dict[str, dict[str, int]] = {}

    for t in data["targets"]:
        for f in t["findings"]:
            # Look up tags for this rule
            rule = db.query(Rule).filter(
                Rule.section_number == f["section_number"],
            ).first()
            tags: list[str] = []
            if rule:
                rule_tags = db.query(RuleTag).filter(RuleTag.rule_id == rule.id).all()
                tags = [rt.tag_id for rt in rule_tags]
            if not tags:
                tags = ["uncategorized"]

            for tag in tags:
                if tag not in category_stats:
                    category_stats[tag] = {"pass": 0, "fail": 0}
                if f["status"] == "PASS":
                    category_stats[tag]["pass"] += 1
                elif f["status"] == "FAIL":
                    category_stats[tag]["fail"] += 1

    lines: list[str] = []
    for cat, stats in sorted(category_stats.items()):
        total = stats["pass"] + stats["fail"]
        compliance = round(stats["pass"] / total * 100, 1) if total > 0 else 0.0
        lines.append(f"  {cat}: {compliance}%")
        lines.append(f"    - {stats['pass']} passed, {stats['fail']} failed")

    return ANALYSIS_CATEGORY.format(
        client_name=data["client"].name if data["client"] else "Unknown",
        mission_name=data["mission"].name,
        categories_data="\n".join(lines) if lines else "  No category data available.",
    )


def _count_by_severity(findings: list[dict[str, Any]], status: str | None = None) -> dict[str, int]:
    """Count findings by severity level, optionally filtering by status."""
    counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        if status and f["status"] != status:
            continue
        sev = (f.get("severity") or "medium").lower()
        if sev in counts:
            counts[sev] += 1
    return counts


def _build_cross_mission_prompt(
    current_data: dict[str, Any],
    previous_data: dict[str, Any],
) -> str:
    """Build the LLM prompt for cross-mission comparison."""
    client_name = current_data["client"].name if current_data["client"] else "Unknown"

    # Gather all findings flat
    current_findings: list[dict[str, Any]] = []
    previous_findings: list[dict[str, Any]] = []
    for t in current_data["targets"]:
        current_findings.extend(t["findings"])
    for t in previous_data["targets"]:
        previous_findings.extend(t["findings"])

    # Compliance
    current_total_pass = sum(t["total_pass"] for t in current_data["targets"])
    current_total = sum(t["total_pass"] + t["total_fail"] for t in current_data["targets"])
    previous_total_pass = sum(t["total_pass"] for t in previous_data["targets"])
    previous_total = sum(t["total_pass"] + t["total_fail"] for t in previous_data["targets"])

    current_compliance = round(current_total_pass / current_total * 100, 1) if current_total > 0 else 0.0
    previous_compliance = round(previous_total_pass / previous_total * 100, 1) if previous_total > 0 else 0.0

    current_sev = _count_by_severity(current_findings, "FAIL")
    previous_sev = _count_by_severity(previous_findings, "FAIL")

    # Identify changes by section_number
    prev_fail_sections = {f["section_number"] for f in previous_findings if f["status"] == "FAIL"}
    prev_pass_sections = {f["section_number"] for f in previous_findings if f["status"] == "PASS"}
    curr_fail_sections = {f["section_number"] for f in current_findings if f["status"] == "FAIL"}
    curr_pass_sections = {f["section_number"] for f in current_findings if f["status"] == "PASS"}

    improved = list(prev_fail_sections & curr_pass_sections)
    regressed = list(prev_pass_sections & curr_fail_sections)
    still_failing = list(prev_fail_sections & curr_fail_sections)

    current_targets = {t["hostname"] for t in current_data["targets"]}
    previous_targets = {t["hostname"] for t in previous_data["targets"]}
    new_targets = list(current_targets - previous_targets)
    removed_targets = list(previous_targets - current_targets)

    return ANALYSIS_CROSS_MISSION.format(
        client_name=client_name,
        previous_mission_name=previous_data["mission"].name,
        previous_date=str(previous_data["mission"].start_date or previous_data["mission"].created_at or "N/A"),
        previous_compliance=previous_compliance,
        previous_critical=previous_sev["critical"],
        previous_high=previous_sev["high"],
        previous_medium=previous_sev["medium"],
        previous_low=previous_sev["low"],
        current_mission_name=current_data["mission"].name,
        current_date=str(current_data["mission"].start_date or current_data["mission"].created_at or "N/A"),
        current_compliance=current_compliance,
        current_critical=current_sev["critical"],
        current_high=current_sev["high"],
        current_medium=current_sev["medium"],
        current_low=current_sev["low"],
        rules_improved=", ".join(improved[:20]) if improved else "None",
        rules_regressed=", ".join(regressed[:20]) if regressed else "None",
        rules_still_failing=", ".join(still_failing[:20]) if still_failing else "None",
        new_targets=", ".join(new_targets) if new_targets else "None",
        removed_targets=", ".join(removed_targets) if removed_targets else "None",
    )


async def run_cross_target_analysis(mission_id: int, db: Session) -> dict[str, Any]:
    """Run cross-target pattern detection analysis."""
    data = _gather_mission_data(mission_id, db)
    if len(data["targets"]) == 0:
        return {
            "systemic_issues": [],
            "outliers": [],
            "risk_chains": [],
            "remediation_plan": [],
            "note": "No targets found in this mission.",
        }

    prompt = _build_cross_target_prompt(data)
    result = await llm_manager.invoke_json(
        prompt,
        system_prompt="You are a cybersecurity audit analyst providing post-mission analysis.",
        timeout=300.0,
        task="analysis",
    )
    return result


async def run_category_analysis(mission_id: int, db: Session) -> dict[str, Any]:
    """Run category-level compliance analysis."""
    data = _gather_mission_data(mission_id, db)
    if len(data["targets"]) == 0:
        return {
            "strengths": [],
            "weaknesses": [],
            "quick_wins": [],
            "strategic_recommendations": [],
            "note": "No targets found in this mission.",
        }

    prompt = _build_category_prompt(data, db)
    result = await llm_manager.invoke_json(
        prompt,
        system_prompt="You are a cybersecurity audit analyst providing category-level analysis.",
        timeout=300.0,
        task="analysis",
    )
    return result


async def run_cross_mission_analysis(
    mission_id: int,
    compare_mission_id: int,
    db: Session,
) -> dict[str, Any]:
    """Run cross-mission comparison analysis."""
    current_data = _gather_mission_data(mission_id, db)
    previous_data = _gather_mission_data(compare_mission_id, db)

    if current_data["mission"].client_id != previous_data["mission"].client_id:
        raise ValueError("Cannot compare missions from different clients")

    prompt = _build_cross_mission_prompt(current_data, previous_data)
    result = await llm_manager.invoke_json(
        prompt,
        system_prompt="You are a cybersecurity audit analyst comparing audit engagements.",
        timeout=300.0,
        task="analysis",
    )
    return result


def get_comparable_missions(client_id: int, db: Session) -> list[dict[str, Any]]:
    """Get missions for a client that can be compared (have at least one scan)."""
    missions = (
        db.query(Mission)
        .filter(Mission.client_id == client_id)
        .order_by(Mission.created_at.desc())
        .all()
    )

    result: list[dict[str, Any]] = []
    for m in missions:
        # Scans now have direct mission_id
        mission_scans = db.query(Scan).filter(Scan.mission_id == m.id).all()
        total_pass = 0
        total_checked = 0
        has_scans = len(mission_scans) > 0

        for s in mission_scans:
            total_pass += s.passed or 0
            total_checked += s.total_rules_checked or 0

        if has_scans:
            compliance = round(total_pass / total_checked * 100, 1) if total_checked > 0 else 0.0
            result.append({
                "id": m.id,
                "name": m.name,
                "start_date": str(m.start_date) if m.start_date else None,
                "end_date": str(m.end_date) if m.end_date else None,
                "compliance": compliance,
            })

    return result
