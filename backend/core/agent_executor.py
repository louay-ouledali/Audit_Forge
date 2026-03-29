"""Agent-based scan executor — runs CIS benchmarks through WebSocket-connected agents."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from backend.connectors.base import CommandResult
from backend.core import agent_registry
from backend.core.comparison_engine import evaluate as evaluate_expression
from backend.core.error_patterns import classify_output

logger = logging.getLogger("auditforge.agent_executor")

# Re-use scan progress tracking pattern from scan_executor
_scan_progress: dict[int, dict] = {}


async def _broadcast_scan_event(session_id: int, event: dict) -> None:
    """Best-effort broadcast scan events to auditor monitors."""
    try:
        from backend.api.ws_agent import _broadcast_to_monitors
        await _broadcast_to_monitors(session_id, event)
    except Exception:
        pass


async def execute_agent_scan(
    db_factory,
    scan_id: int,
    agent_token: str,
    benchmark_id: int,
    selected_rule_ids: list[int] | None = None,
) -> None:
    """Execute a CIS benchmark scan via a connected agent's WebSocket channel.

    This mirrors the logic of ``scan_executor.execute_network_scan`` but
    routes commands through the agent WebSocket instead of SSH/WinRM.
    """
    from backend.models.benchmark import Benchmark
    from backend.models.finding import Finding
    from backend.models.rule import Rule
    from backend.models.rule_command import RuleCommand
    from backend.models.scan import Scan
    from backend.api.ws_agent import register_command_future

    db = db_factory()

    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            logger.error("Scan %d not found", scan_id)
            return

        benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
        if not benchmark:
            scan.status = "failed"
            db.commit()
            return

        # Get the live agent
        live = agent_registry.get_by_token(agent_token)
        if not live:
            scan.status = "failed"
            db.commit()
            return

        session_id = live.session_id

        # Load rules
        rules_q = (
            db.query(Rule)
            .filter(Rule.benchmark_id == benchmark_id)
            .order_by(Rule.section_number)
        )
        rules = rules_q.all()

        if selected_rule_ids:
            rules = [r for r in rules if r.id in selected_rule_ids]

        total = len(rules)
        passed = 0
        failed = 0
        errors = 0
        checked = 0

        _scan_progress[scan_id] = {
            "total": total,
            "completed": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "status": "running",
        }

        scan.total_rules = total
        scan.status = "running"
        db.commit()

        # Broadcast scan started
        await _broadcast_scan_event(session_id, {
            "type": "scan_progress",
            "payload": {"agent_id": live.agent_id, "scan_id": scan_id, "completed": 0, "total": total},
        })

        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 20

        for rule in rules:
            # Check agent is still alive before each command
            if not agent_registry.get_by_token(agent_token):
                logger.warning("Scan %d: agent disconnected mid-scan — aborting", scan_id)
                break

            cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule.id).first()
            if not cmd or not cmd.audit_command:
                continue

            audit_command = cmd.audit_command.strip()
            expected = cmd.expected_output_regex or ""

            # Send command to agent via WebSocket
            cmd_id = str(uuid.uuid4())
            try:
                future = register_command_future(agent_token, cmd_id)
                await live.websocket.send_json({
                    "type": "command",
                    "payload": {
                        "id": cmd_id,
                        "command": audit_command,
                        "timeout": 30,
                    },
                })

                # Wait for result
                result_payload = await asyncio.wait_for(future, timeout=35)

                result = CommandResult(
                    stdout=result_payload.get("stdout", ""),
                    stderr=result_payload.get("stderr", ""),
                    exit_code=result_payload.get("exit_code", 0),
                    execution_time_ms=result_payload.get("execution_time_ms", 0),
                )

            except asyncio.TimeoutError:
                result = CommandResult(
                    stdout="", stderr="Agent command timed out", exit_code=-1
                )
            except Exception as exc:
                result = CommandResult(
                    stdout="", stderr=str(exc), exit_code=-1
                )

            # Evaluate result (same logic as scan_executor._evaluate_result)
            status, explanation = _evaluate_result(result, expected or None)

            checked += 1
            if status == "PASS":
                passed += 1
                consecutive_errors = 0
            elif status == "FAIL":
                failed += 1
                consecutive_errors = 0
            else:
                errors += 1
                consecutive_errors += 1

            # Store finding
            finding = Finding(
                scan_id=scan_id,
                rule_id=rule.id,
                status=status,
                actual_output=result.stdout[:4000] if result.stdout else result.stderr[:4000],
                expected_output=expected,
                severity=rule.severity or "medium",
                evaluation_explanation=explanation,
            )
            db.add(finding)

            # Update progress
            _scan_progress[scan_id] = {
                "total": total,
                "completed": checked,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "status": "running",
            }

            # Broadcast progress every 5 rules
            if checked % 5 == 0 or checked == total:
                await _broadcast_scan_event(session_id, {
                    "type": "scan_progress",
                    "payload": {
                        "agent_id": live.agent_id,
                        "scan_id": scan_id,
                        "completed": checked,
                        "total": total,
                        "current_rule": rule.section_number,
                    },
                })

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.warning("Scan %d: %d consecutive errors — aborting", scan_id, consecutive_errors)
                break

        # Finalize scan
        compliance = (passed / checked * 100) if checked > 0 else 0
        scan.status = "completed"
        scan.total_rules_checked = checked
        scan.passed = passed
        scan.failed = failed
        scan.errors = errors
        scan.compliance_percentage = round(compliance, 1)
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()

        _scan_progress[scan_id]["status"] = "completed"
        _scan_progress[scan_id]["compliance"] = scan.compliance_percentage

        # Persist agent open_ports to DiscoveryCache
        try:
            from backend.models.connect_agent import ConnectAgent
            from backend.models.discovery_cache import DiscoveryCache

            ag = db.query(ConnectAgent).filter(ConnectAgent.token == agent_token).first()
            if ag and ag.system_info:
                sys_info = json.loads(ag.system_info)
                agent_ports = sys_info.get("open_ports", [])
                ip = ag.ip_address or (sys_info.get("ip_addresses", [None])[0] if sys_info.get("ip_addresses") else None)
                if ip and agent_ports:
                    open_ports_data = [
                        {"port": p, "service": "", "platform_hint": ""}
                        for p in agent_ports if isinstance(p, int)
                    ]
                    now = datetime.now(timezone.utc)
                    cached = db.query(DiscoveryCache).filter(
                        DiscoveryCache.ip_address == ip
                    ).order_by(DiscoveryCache.last_seen.desc()).first()
                    if cached:
                        cached.hostname = ag.hostname or cached.hostname
                        cached.os_guess = "windows" if "windows" in (ag.os_type or "").lower() else "linux"
                        cached.detection_method = "agent_scan"
                        cached.last_seen = now
                        cached.open_ports_json = json.dumps(open_ports_data)
                    else:
                        db.add(DiscoveryCache(
                            ip_address=ip,
                            hostname=ag.hostname,
                            os_guess="windows" if "windows" in (ag.os_type or "").lower() else "linux",
                            os_version=ag.os_version,
                            detection_method="agent_scan",
                            first_seen=now,
                            last_seen=now,
                            open_ports_json=json.dumps(open_ports_data),
                        ))
                    db.commit()
        except Exception:
            logger.debug("Failed to persist agent port data to DiscoveryCache", exc_info=True)

        # Broadcast completion
        await _broadcast_scan_event(session_id, {
            "type": "scan_complete",
            "payload": {
                "agent_id": live.agent_id,
                "scan_id": scan_id,
                "pass": passed,
                "fail": failed,
                "error": errors,
                "compliance_percentage": round(compliance, 1),
                "total_rules_checked": checked,
                "benchmark_name": benchmark.name,
            },
        })

        # Update agent status back to connected (or completed if disconnected)
        try:
            from backend.models.connect_agent import ConnectAgent
            ag = db.query(ConnectAgent).filter(ConnectAgent.token == agent_token).first()
            if ag and ag.status == "scanning":
                ag.status = "completed" if not agent_registry.get_by_token(agent_token) else "connected"
                db.commit()
        except Exception:
            pass

        logger.info(
            "Agent scan %d completed: %d/%d checked, %.1f%% compliant",
            scan_id, checked, total, compliance,
        )

    except Exception as exc:
        logger.error("Agent scan %d failed: %s", scan_id, exc)
        try:
            scan = db.query(Scan).filter(Scan.id == scan_id).first()
            if scan:
                scan.status = "failed"
                db.commit()
        except Exception:
            pass
        _scan_progress.pop(scan_id, None)
    finally:
        db.close()


def _evaluate_result(result: CommandResult, expected_regex: str | None) -> tuple[str, str]:
    """Evaluate a command result — mirrors scan_executor._evaluate_result exactly."""
    stdout_text = result.stdout or ""
    stderr_text = result.stderr or ""
    combined_output = (stdout_text + "\n" + stderr_text).strip()
    output_text = stdout_text if stdout_text.strip() else stderr_text
    output_stripped = output_text.strip() if output_text else ""

    # Tier 0: Total failure — non-zero exit and no output at all
    if result.exit_code != 0 and not combined_output:
        return "ERROR", f"Command failed with exit code {result.exit_code}"

    # Tier 1: Execution error (bad command, access denied, etc.)
    category = classify_output(combined_output)
    if category == "execution_error":
        if expected_regex and output_stripped:
            comp_result = evaluate_expression(expected_regex, output_text)
            if comp_result.matched:
                return "PASS", f"Evaluated from output despite execution markers: {comp_result.explanation}"
            return "FAIL", f"Evaluated from output despite execution markers: {comp_result.explanation}"
        return "ERROR", "Command execution error detected in output"

    # Tier 2: Not configured
    if category == "not_configured":
        if "no such file or directory" in combined_output.lower():
            return "FAIL", "Required file/path missing on target"
        if expected_regex:
            comp_result = evaluate_expression(expected_regex, "")
            if comp_result.matched:
                return "PASS", f"Not Configured - but expression matched empty: {comp_result.explanation}"
            return "FAIL", "Not Configured (registry key/GPO path missing)"
        return "FAIL", "Not Configured (registry key/GPO path missing)"

    # Tier 2b: Service not found → treat as Disabled
    if category == "service_not_found":
        if expected_regex:
            comp_result = evaluate_expression(expected_regex, "Disabled")
            if comp_result.matched:
                return "PASS", "Service not installed (treated as Disabled)"
            return "FAIL", "Service not installed"
        return "FAIL", "Service not installed"

    # Tier 2c: Module not found → secure
    if category == "module_not_found":
        return "PASS", "Kernel module not found on system (equivalent to disabled)"

    # Tier 3: Normal evaluation via comparison engine
    if not expected_regex:
        if result.exit_code != 0 and not (stdout_text.strip() if stdout_text else ""):
            return "ERROR", f"Command failed with exit code {result.exit_code}"
        if result.exit_code == 0:
            return "PASS", "Command executed successfully (no expected output defined)"
        return "FAIL", f"Command failed with exit code {result.exit_code}"

    comp_result = evaluate_expression(expected_regex, output_text)
    if comp_result.matched:
        return "PASS", comp_result.explanation
    return "FAIL", comp_result.explanation
