"""Forge Resolve — core remediation engine.

Handles:
- Building remediation items from FAIL findings
- Generating remediation script ZIPs (air-gapped)
- Executing remediation commands (network live / agent)
- Multi-scan intelligence (delta + AI insights)
- CSV export of results
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.connectors import get_connector
from backend.connectors.base import CommandResult
from backend.models.finding import Finding
from backend.models.remediation_item import RemediationItem
from backend.models.remediation_session import RemediationSession
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.scan import Scan
from backend.models.target import Target
from backend.core.trail import log_action
from backend.utils.encryption import decrypt_value
from backend.config import settings

logger = logging.getLogger("auditforge.resolve")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Patterns indicating privileged commands
_PRIVILEGE_PATTERNS = [
    r"\bsudo\b", r"\brunas\b", r"\bchmod\b", r"\bchown\b",
    r"\biptables\b", r"\bufw\b", r"\bfirewall-cmd\b",
    r"\bsystemctl\b", r"\bservice\s+\w+\s+(start|stop|restart|enable|disable)",
    r"\bnet\s+accounts\b", r"\bsecedit\b", r"\bauditpol\b",
    r"\bSet-Service\b", r"\bSet-ItemProperty\b", r"\bNew-ItemProperty\b",
    r"\bReg\s+Add\b", r"-RunAsAdministrator",
    r"\bGRANT\b", r"\bREVOKE\b", r"\bALTER\s+SYSTEM\b",
]

_PRIVILEGE_RE = re.compile("|".join(_PRIVILEGE_PATTERNS), re.IGNORECASE)


# ── Build Remediation Items ──────────────────────────────────────────

def build_remediation_items(
    scan_ids: list[int],
    target_id: int,
    db: Session,
) -> list[dict]:
    """Collect FAIL findings from given scans, deduplicate by rule, return item dicts."""
    # Load findings, newest scan first so latest status wins
    findings = (
        db.query(Finding)
        .join(Scan, Finding.scan_id == Scan.id)
        .filter(
            Finding.scan_id.in_(scan_ids),
            Scan.target_id == target_id,
            Finding.status == "FAIL",
        )
        .order_by(Scan.completed_at.desc())
        .all()
    )

    # Deduplicate by rule_id — keep latest
    seen_rules: set[int] = set()
    unique_findings: list[Finding] = []
    for f in findings:
        if f.rule_id and f.rule_id not in seen_rules:
            seen_rules.add(f.rule_id)
            unique_findings.append(f)

    items: list[dict] = []
    for idx, finding in enumerate(unique_findings):
        rule = db.query(Rule).filter(Rule.id == finding.rule_id).first()
        if not rule:
            continue

        cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule.id).first()

        # Determine remediation command and source
        rem_cmd = ""
        source = "benchmark"
        transport = "shell"

        if cmd and cmd.remediation_command and cmd.remediation_command.strip():
            rem_cmd = cmd.remediation_command.strip()
            source = "benchmark"
            transport = cmd.command_transport or "shell"
        elif rule.remediation_description_raw and rule.remediation_description_raw.strip():
            rem_cmd = rule.remediation_description_raw.strip()
            source = "cis_text"
            transport = cmd.command_transport or "shell" if cmd else "shell"

        # Detect privilege requirement
        requires_priv = bool(_PRIVILEGE_RE.search(rem_cmd)) if rem_cmd else False

        items.append({
            "finding_id": finding.id,
            "rule_id": rule.id,
            "section_number": rule.section_number or "",
            "rule_title": rule.title or "",
            "severity": finding.severity or rule.severity or "medium",
            "remediation_command": rem_cmd,
            "command_source": source,
            "command_transport": transport,
            "selected": bool(rem_cmd and source == "benchmark"),
            "status": "pending",
            "order_index": idx,
            "requires_privilege": requires_priv,
        })

    return items


# ── Script Generation (Air-Gapped) ──────────────────────────────────

def _get_jinja_env():
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape([]),
        keep_trailing_newline=True,
    )


def generate_remediation_script(
    session: RemediationSession,
    items: list[RemediationItem],
    target: Target,
    db: Session,
) -> tuple[bytes, str]:
    """Generate a ZIP with remediation script for selected items."""
    selected = [i for i in items if i.selected and i.remediation_command]
    if not selected:
        raise ValueError("No selected items with remediation commands")

    # Determine platform template
    target_type = (target.target_type or "linux").lower()
    if target_type in ("windows", "sharepoint"):
        template_name = "resolve_powershell.ps1.j2"
        script_filename = "remediate.ps1"
    elif target_type in ("postgresql", "oracle", "mssql", "mysql", "mongodb"):
        template_name = "resolve_sql.sql.j2"
        script_filename = "remediate.sql"
    else:
        template_name = "resolve_bash.sh.j2"
        script_filename = "remediate.sh"

    env = _get_jinja_env()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    items_dicts = [
        {
            "index": idx + 1,
            "section_number": i.section_number,
            "rule_title": i.rule_title,
            "severity": i.severity or "medium",
            "remediation_command": i.remediation_command,
            "command_transport": i.command_transport or "shell",
            "requires_privilege": i.requires_privilege,
        }
        for idx, i in enumerate(selected)
    ]

    context = {
        "target": {
            "hostname": target.hostname or target.ip_address or "unknown",
            "ip": target.ip_address or "",
            "platform": target.target_type or "linux",
        },
        "session_id": session.id,
        "items": items_dicts,
        "total": len(items_dicts),
        "generation_date": now_str,
    }

    try:
        template = env.get_template(template_name)
    except Exception:
        template = env.get_template("resolve_bash.sh.j2")
        script_filename = "remediate.sh"

    script_content = template.render(**context)

    # Build reference JSON
    reference = json.dumps(items_dicts, indent=2, default=str)

    # README
    try:
        readme_tpl = env.get_template("resolve_readme.txt.j2")
        readme_content = readme_tpl.render(**context)
    except Exception:
        readme_content = f"AuditForge Remediation Package\nTarget: {context['target']['hostname']}\nGenerated: {now_str}\nCommands: {len(items_dicts)}\n"

    # Build ZIP
    safe_host = re.sub(r"[^\w.-]", "_", target.hostname or target.ip_address or "target")
    folder = f"auditforge_resolve_{safe_host}_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    zip_filename = f"{folder}.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        content = ("\ufeff" + script_content) if script_filename.endswith(".ps1") else script_content
        zf.writestr(f"{folder}/{script_filename}", content)
        zf.writestr(f"{folder}/remediation_reference.json", reference)
        zf.writestr(f"{folder}/README.txt", readme_content)

    return buf.getvalue(), zip_filename


# ── Network Live Execution ───────────────────────────────────────────

async def execute_remediation_network(
    session_id: int,
    db: Session,
    user: Any = None,
) -> None:
    """Execute approved remediation commands on target via network connector."""
    session = db.query(RemediationSession).filter(RemediationSession.id == session_id).first()
    if not session:
        raise ValueError(f"Session {session_id} not found")

    target = db.query(Target).filter(Target.id == session.target_id).first()
    if not target:
        raise ValueError(f"Target {session.target_id} not found")

    selected_items = (
        db.query(RemediationItem)
        .filter(RemediationItem.session_id == session_id, RemediationItem.selected == True)
        .order_by(RemediationItem.order_index)
        .all()
    )

    if not selected_items:
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        db.commit()
        return

    session.status = "executing"
    session.execution_mode = "network"
    session.executed_at = datetime.now(timezone.utc)
    db.commit()

    connector = None
    succeeded = 0
    failed = 0

    try:
        # Decrypt credentials
        password = None
        if target.ssh_password_encrypted:
            try:
                password = decrypt_value(target.ssh_password_encrypted, settings.SECRET_KEY)
            except Exception:
                pass
        target._decrypted_password = password

        # Connect
        connector = get_connector(target.target_type or "linux", target.connection_method)
        await connector.connect(target)

        for item in selected_items:
            if not item.remediation_command:
                item.status = "skipped"
                db.commit()
                continue

            item.status = "executing"
            db.commit()

            try:
                cmd = item.remediation_command
                # Auto-prefix sudo for Linux shell commands
                target_type_lower = (target.target_type or "").lower()
                if item.command_transport == "shell" and target_type_lower in ("linux", "cassandra"):
                    if not cmd.strip().startswith("sudo "):
                        cmd = f"sudo {cmd}"

                result: CommandResult = await connector.execute(cmd, timeout=30)

                item.execution_output = (result.stdout or "")[:4000]
                item.execution_error = (result.stderr or "")[:4000]
                item.executed_at = datetime.now(timezone.utc)

                if result.exit_code == 0:
                    item.status = "success"
                    succeeded += 1
                else:
                    item.status = "failed"
                    failed += 1

                log_action(
                    db, user=user, mission_id=session.mission_id,
                    action="resolve_command_executed",
                    entity_type="remediation_item", entity_id=item.id,
                    entity_label=item.section_number,
                    details={"status": item.status, "exit_code": result.exit_code},
                )
                db.commit()

            except Exception as exc:
                item.status = "failed"
                item.execution_error = str(exc)[:4000]
                item.executed_at = datetime.now(timezone.utc)
                failed += 1
                db.commit()

    except Exception as exc:
        logger.error("Remediation execution failed: %s", exc)
        session.status = "failed"
        session.notes = f"Connection/execution error: {str(exc)[:500]}"
    else:
        session.status = "completed"
    finally:
        if connector:
            try:
                await connector.disconnect()
            except Exception:
                pass

        session.succeeded_items = succeeded
        session.failed_items = failed
        session.skipped_items = session.total_items - succeeded - failed
        session.completed_at = datetime.now(timezone.utc)
        db.commit()


# ── WebSocket Agent Execution ────────────────────────────────────────

async def execute_remediation_agent(
    session_id: int,
    agent_id: int,
    db: Session,
    user: Any = None,
) -> None:
    """Execute approved remediation commands via WebSocket agent."""
    from backend.core.agent_registry import get_by_session
    from backend.api.ws_agent import register_command_future

    session = db.query(RemediationSession).filter(RemediationSession.id == session_id).first()
    if not session:
        raise ValueError(f"Session {session_id} not found")

    # Find the live agent
    agents = get_by_session(agent_id)
    if not agents:
        raise ValueError(f"No live agent found for session {agent_id}")
    live = agents[0]

    selected_items = (
        db.query(RemediationItem)
        .filter(RemediationItem.session_id == session_id, RemediationItem.selected == True)
        .order_by(RemediationItem.order_index)
        .all()
    )

    session.status = "executing"
    session.execution_mode = "agent"
    session.executed_at = datetime.now(timezone.utc)
    db.commit()

    succeeded = 0
    failed = 0

    for item in selected_items:
        if not item.remediation_command:
            item.status = "skipped"
            db.commit()
            continue

        item.status = "executing"
        db.commit()

        cmd_id = str(uuid.uuid4())
        try:
            future = register_command_future(live.websocket, cmd_id)
            await live.websocket.send_json({
                "type": "command",
                "payload": {
                    "id": cmd_id,
                    "command": item.remediation_command,
                    "timeout": 30,
                },
            })

            result_payload = await asyncio.wait_for(future, timeout=35)

            item.execution_output = (result_payload.get("stdout", "") or "")[:4000]
            item.execution_error = (result_payload.get("stderr", "") or "")[:4000]
            item.executed_at = datetime.now(timezone.utc)

            if result_payload.get("exit_code", -1) == 0:
                item.status = "success"
                succeeded += 1
            else:
                item.status = "failed"
                failed += 1

        except asyncio.TimeoutError:
            item.status = "failed"
            item.execution_error = "Agent command timed out"
            item.executed_at = datetime.now(timezone.utc)
            failed += 1
        except Exception as exc:
            item.status = "failed"
            item.execution_error = str(exc)[:4000]
            item.executed_at = datetime.now(timezone.utc)
            failed += 1

        log_action(
            db, user=user, mission_id=session.mission_id,
            action="resolve_agent_command_executed",
            entity_type="remediation_item", entity_id=item.id,
            entity_label=item.section_number,
            details={"status": item.status},
        )
        db.commit()

    session.status = "completed" if failed == 0 else "failed" if succeeded == 0 else "completed"
    session.succeeded_items = succeeded
    session.failed_items = failed
    session.skipped_items = session.total_items - succeeded - failed
    session.completed_at = datetime.now(timezone.utc)
    db.commit()


# ── Multi-Scan Intelligence ──────────────────────────────────────────

def build_scan_intelligence(
    target_id: int,
    scan_ids: list[int],
    db: Session,
) -> dict:
    """Build smart delta view + AI insights for multiple scans of the same target."""
    scans = (
        db.query(Scan)
        .filter(Scan.id.in_(scan_ids), Scan.target_id == target_id)
        .order_by(Scan.completed_at.asc())
        .all()
    )

    if not scans:
        return {"scans": [], "changed_rules": [], "consistent_rules": []}

    # Build scan summaries
    scan_summaries = []
    for s in scans:
        scan_summaries.append({
            "scan_id": s.id,
            "date": s.completed_at.isoformat() if s.completed_at else s.created_at.isoformat(),
            "compliance": s.compliance_percentage or 0,
            "passed": s.passed or 0,
            "failed": s.failed or 0,
            "errors": s.errors or 0,
        })

    # Build per-rule status maps
    rule_histories: dict[int, list[dict]] = {}  # rule_id -> [scan status entries]
    rule_info: dict[int, dict] = {}  # rule_id -> {section, title, severity, rem_cmd}

    for s in scans:
        findings = (
            db.query(Finding)
            .filter(Finding.scan_id == s.id)
            .all()
        )
        for f in findings:
            if not f.rule_id:
                continue
            if f.rule_id not in rule_histories:
                rule_histories[f.rule_id] = []
                # Load rule info once
                rule = db.query(Rule).filter(Rule.id == f.rule_id).first()
                cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == f.rule_id).first() if rule else None
                rem = (cmd.remediation_command or "").strip() if cmd else ""
                rule_info[f.rule_id] = {
                    "section_number": rule.section_number if rule else "",
                    "title": rule.title if rule else "",
                    "severity": f.severity or (rule.severity if rule else "medium"),
                    "remediation_command": rem,
                    "has_executable_command": bool(rem),
                }

            rule_histories[f.rule_id].append({
                "scan_id": s.id,
                "status": f.status,
                "date": s.completed_at.isoformat() if s.completed_at else "",
            })

    # Classify rules
    changed_rules = []
    consistent_rules = []
    improved = regressed = unchanged = new_count = removed = 0

    for rule_id, history in rule_histories.items():
        info = rule_info.get(rule_id, {})
        statuses = [h["status"] for h in history]
        unique_statuses = set(statuses)

        if len(history) == 1 and len(scans) > 1:
            # Rule only appeared in one scan
            change_type = "new" if history[0]["scan_id"] == scans[-1].id else "removed"
            if change_type == "new":
                new_count += 1
            else:
                removed += 1
        elif len(unique_statuses) > 1:
            # Status changed
            first = statuses[0]
            last = statuses[-1]
            if first == "FAIL" and last == "PASS":
                change_type = "improved"
                improved += 1
            elif first == "PASS" and last == "FAIL":
                change_type = "regressed"
                regressed += 1
            else:
                change_type = "improved" if last == "PASS" else "regressed"
                if last == "PASS":
                    improved += 1
                else:
                    regressed += 1
        else:
            change_type = "unchanged"
            unchanged += 1

        delta_rule = {
            "rule_id": rule_id,
            "section_number": info.get("section_number", ""),
            "title": info.get("title", ""),
            "severity": info.get("severity", "medium"),
            "history": history,
            "change_type": change_type,
            "remediation_command": info.get("remediation_command"),
            "has_executable_command": info.get("has_executable_command", False),
        }

        if change_type == "unchanged":
            consistent_rules.append(delta_rule)
        else:
            changed_rules.append(delta_rule)

    # Time intervals between scans
    time_intervals = []
    for i in range(1, len(scans)):
        prev_dt = scans[i - 1].completed_at or scans[i - 1].created_at
        curr_dt = scans[i].completed_at or scans[i].created_at
        if prev_dt and curr_dt:
            delta = curr_dt - prev_dt
            days = delta.days
            if days == 0:
                hours = delta.seconds // 3600
                time_intervals.append(f"{hours} hours" if hours > 1 else f"{delta.seconds // 60} minutes")
            elif days < 7:
                time_intervals.append(f"{days} days")
            elif days < 30:
                time_intervals.append(f"{days // 7} weeks")
            else:
                time_intervals.append(f"{days // 30} months")

    # Compliance trend
    compliance_trend = [
        {"scan_id": s["scan_id"], "date": s["date"], "compliance": s["compliance"]}
        for s in scan_summaries
    ]

    # AI Insights (optional — only if LLM is available)
    ai_insights = _generate_ai_insights(
        scan_summaries, changed_rules, improved, regressed, unchanged, db
    )

    return {
        "scans": scan_summaries,
        "time_intervals": time_intervals,
        "compliance_trend": compliance_trend,
        "rules_improved": improved,
        "rules_regressed": regressed,
        "rules_unchanged": unchanged,
        "rules_new": new_count,
        "rules_removed": removed,
        "changed_rules": changed_rules,
        "consistent_rules": consistent_rules,
        "ai_insights": ai_insights,
    }


def _generate_ai_insights(
    scans: list[dict],
    changed_rules: list[dict],
    improved: int,
    regressed: int,
    unchanged: int,
    db: Session,
) -> dict | None:
    """Generate AI insights from scan delta data."""
    if len(scans) < 2:
        return None

    try:
        from backend.core.llm_client import call_llm
    except ImportError:
        return None

    trend = scans[-1]["compliance"] - scans[0]["compliance"]
    regressed_rules = [r for r in changed_rules if r["change_type"] == "regressed"]
    improved_rules = [r for r in changed_rules if r["change_type"] == "improved"]

    prompt = f"""Analyze these compliance scan results for a configuration review:

Scans: {len(scans)} scans over time
Compliance trend: {scans[0]['compliance']:.1f}% → {scans[-1]['compliance']:.1f}% ({'+' if trend >= 0 else ''}{trend:.1f}%)
Rules improved (FAIL→PASS): {improved}
Rules regressed (PASS→FAIL): {regressed}
Rules unchanged: {unchanged}

Top regressed rules: {json.dumps([{'section': r['section_number'], 'title': r['title'], 'severity': r['severity']} for r in regressed_rules[:10]], indent=2)}
Top improved rules: {json.dumps([{'section': r['section_number'], 'title': r['title']} for r in improved_rules[:5]], indent=2)}

Provide a JSON response with:
- "summary": 2-3 sentence executive summary
- "risk_trajectory": "improving" or "stable" or "declining"
- "patterns": array of 2-4 notable pattern observations (ports, recurring failures, systemic issues)
- "priority_remediations": array of 2-4 top priority remediation recommendations
Return ONLY valid JSON, no markdown."""

    try:
        response = call_llm(prompt, db=db, max_tokens=500)
        return json.loads(response)
    except Exception as exc:
        logger.warning("AI insights generation failed: %s", exc)
        # Fallback static insights
        trajectory = "improving" if trend > 2 else "declining" if trend < -2 else "stable"
        return {
            "summary": f"Compliance moved from {scans[0]['compliance']:.1f}% to {scans[-1]['compliance']:.1f}% across {len(scans)} scans. {improved} rules improved, {regressed} regressed.",
            "risk_trajectory": trajectory,
            "patterns": [
                f"{regressed} rules regressed — review for configuration drift" if regressed > 0 else "No regressions detected",
                f"{improved} rules improved since first scan" if improved > 0 else "No improvements detected",
            ],
            "priority_remediations": [
                f"Address {r['section_number']}: {r['title']}"
                for r in regressed_rules[:4]
            ] if regressed_rules else ["All previously failing rules are stable or improved"],
        }


# ── CSV Export ────────────────────────────────────────────────────────

def export_results_csv(session_id: int, db: Session) -> bytes:
    """Export remediation results as CSV."""
    items = (
        db.query(RemediationItem)
        .filter(RemediationItem.session_id == session_id)
        .order_by(RemediationItem.order_index)
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Section", "Rule", "Severity", "Command", "Source",
        "Selected", "Status", "Output", "Error", "Executed At",
    ])

    for item in items:
        writer.writerow([
            item.section_number,
            item.rule_title,
            item.severity or "",
            item.remediation_command or "",
            item.command_source,
            "Yes" if item.selected else "No",
            item.status,
            (item.execution_output or "")[:500],
            (item.execution_error or "")[:500],
            item.executed_at.isoformat() if item.executed_at else "",
        ])

    return output.getvalue().encode("utf-8-sig")
