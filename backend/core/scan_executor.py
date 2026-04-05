"""Scan executor — orchestrates network scan execution.

Responsible for:
1. Connecting to the target via the appropriate connector
2. Running selected rules' audit commands
3. Evaluating results against expected output regex
4. Storing findings in the database
5. Tracking progress for live UI updates
"""

from __future__ import annotations

import asyncio
import json
import logging
import re  # UNUSED — safe to remove
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.config import settings
from backend.connectors import get_connector
from backend.connectors.base import BaseConnector, CommandResult
from backend.connectors.ssh_connector import SSHConnector
from backend.connectors.winrm_connector import WinRMConnector
from backend.core.comparison_engine import evaluate as evaluate_expression
from backend.core.error_patterns import classify_output, is_execution_error
from backend.core.exceptions import ConnectionFailedError, ScanCancelledError  # UNUSED: 'ConnectionFailedError', 'ScanCancelledError' — safe to remove
from backend.models.discovery_cache import DiscoveryCache
from backend.models.benchmark import Benchmark
from backend.models.finding import Finding
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.scan import Scan
from backend.models.target import Target
from backend.utils.encryption import decrypt_value

logger = logging.getLogger("auditforge.scan_executor")

# Statuses that should be skipped during scanning
_SKIP_STATUSES = {"skipped", "manual", "not_applicable"}

# Commands that already run with elevated privileges or shouldn't be prefixed
_SUDO_SKIP_PREFIXES = ("sudo ", "cat ", "echo ", "printf ", "id ", "whoami ", "uname ")

# Target types that use a SQL-based primary connector
_DATABASE_TARGET_TYPES = {"postgresql", "oracle", "mssql", "mysql", "mongodb"}


def _infer_transport(cmd: str, target_type: str) -> str:
    """Infer the command transport from command content and target type.

    Returns one of: 'sql', 'shell', 'powershell', 'cli'.
    """
    stripped = cmd.strip()
    upper = stripped.upper()

    # SQL patterns
    if upper.startswith(("SELECT ", "SHOW ", "EXEC ", "WITH ", "DBCC ", "GRANT ", "REVOKE ",
                          "ALTER ", "CREATE ", "DROP ", "SET ", "USE ", "DECLARE ",
                          "sp_configure", "xp_")):
        return "sql"
    # MongoDB shell commands routed through MongoDBConnector
    if stripped.startswith(("db.", "rs.", "sh.")):
        return "sql"

    # Shell patterns
    if stripped.startswith(("grep ", "awk ", "cat ", "stat ", "systemctl ", "ls ",
                            "find ", "chmod ", "chown ", "mount ", "df ",
                            "ps ", "netstat ", "ss ", "sysctl ", "journalctl ",
                            "auditctl ", "sestatus ", "getenforce ",
                            "psql ", "mysql ", "mongosh ", "mongo ", "cqlsh ",
                            "openssl ", "dpkg ", "rpm ", "apt ", "dnf ", "yum ",
                            "fw ")):
        return "shell"
    if stripped.startswith(("sudo ", "/usr/", "/bin/", "/sbin/", "/opt/", "/etc/")):
        return "shell"

    # PowerShell patterns
    if any(kw in stripped for kw in ("Get-ItemProperty", "Get-Service", "Get-VM",
                                      "Get-VMHost", "Get-AdvancedSetting",
                                      "$env:", "Invoke-Sqlcmd", "Get-Acl",
                                      "Get-SPManagedAccount", "Get-WebBinding",
                                      "ForEach-Object", "Select-Object",
                                      "Write-Output", "Format-List")):
        return "powershell"

    # Network device CLI patterns
    if stripped.startswith(("show ", "get system ", "get firewall ",
                            "config ", "execute ", "diagnose ",
                            "diag ", "clish ", "display ")):
        return "cli"

    # Default based on target type
    tt = target_type.lower()
    if tt in _DATABASE_TARGET_TYPES:
        return "sql"
    if tt in ("windows", "sharepoint"):
        return "powershell"
    if tt in ("linux", "cassandra", "vmware_esxi"):
        return "shell"
    if tt in ("cisco_ios", "cisco_asa", "juniper", "fortinet", "palo_alto",
              "arista", "hp_procurve", "checkpoint", "pfsense"):
        return "cli"

    return "shell"


def _prepare_linux_command(cmd: str) -> str:
    """Prepend ``sudo`` to a Linux command if it doesn't already have it.

    Many CIS audit commands read root-owned files (``/etc/ssh/sshd_config``,
    ``/boot/grub/grub.cfg``, ``/etc/audit/auditd.conf``, …) or run tools
    that need root.  The SSH user typically has NOPASSWD sudo configured,
    so we wrap the entire command in ``sudo sh -c '…'`` to ensure privilege.
    """
    stripped = cmd.strip()
    if not stripped:
        return cmd

    # Already has sudo
    if stripped.startswith("sudo "):
        return cmd

    # Simple read commands that don't need root
    if stripped.startswith(_SUDO_SKIP_PREFIXES):
        return cmd

    # Wrap in sudo sh -c to preserve pipes, redirects, globs
    # Escape single quotes in the command
    escaped = stripped.replace("'", "'\\''")
    return f"sudo sh -c '{escaped}'"

# In-memory progress tracking for active scans (scan_id -> progress dict)
_scan_progress: dict[int, dict[str, Any]] = {}
_progress_lock = threading.Lock()

# Set of scan IDs that have been cancelled
_cancelled_scans: set[int] = set()

# Maximum consecutive command execution errors before aborting
MAX_CONSECUTIVE_ERRORS = 20


def get_scan_progress(scan_id: int) -> dict[str, Any] | None:
    """Return current progress for an active scan, or None."""
    with _progress_lock:
        prog = _scan_progress.get(scan_id)
        return dict(prog) if prog else None


def cancel_scan(scan_id: int) -> bool:
    """Mark a scan as cancelled.  Returns True if the scan was active."""
    with _progress_lock:
        if scan_id in _scan_progress:
            _cancelled_scans.add(scan_id)
            return True
    return False


async def _refresh_target_discovery(target: Target, db: Session) -> None:
    """Quick TCP port scan on a target and upsert into DiscoveryCache.

    This runs after every audit scan so that device profile data in reports is
    always up-to-date, even if the user never ran a full network discovery.
    """
    from backend.core.network_discovery import (
        PROBE_PORTS,
        _probe_port,
        _grab_banners,
        _enrich_ports_from_banners,
        _guess_os,
        _detect_connection_methods,
        _reverse_dns,
        MAX_CONCURRENT_PORTS,
    )

    ip = target.ip_address
    if not ip:
        return

    try:
        # Quick TCP port scan
        port_sem = asyncio.Semaphore(MAX_CONCURRENT_PORTS)

        async def _guarded(port: int) -> bool:
            async with port_sem:
                return await _probe_port(ip, port, timeout=1.5)

        results = await asyncio.gather(*[_guarded(p) for p, _, _ in PROBE_PORTS])

        open_ports: list[dict] = []
        for (port, service, hint), is_open in zip(PROBE_PORTS, results):
            if is_open:
                open_ports.append({"port": port, "service": service, "platform_hint": hint})

        # Banner grabbing
        banners: dict[int, str] = {}
        if open_ports:
            banners = await _grab_banners(ip, open_ports)
            _enrich_ports_from_banners(open_ports, banners)

        hostname = await _reverse_dns(ip)
        os_guess = _guess_os(open_ports) if open_ports else "unknown"
        conn_methods = _detect_connection_methods(os_guess, open_ports)

        # Upsert into DiscoveryCache
        now = datetime.now(timezone.utc)
        mac = (target.mac_address or "").upper() or None

        cached: DiscoveryCache | None = None
        if mac:
            cached = (
                db.query(DiscoveryCache)
                .filter(DiscoveryCache.mac_address == mac)
                .order_by(DiscoveryCache.last_seen.desc())
                .first()
            )
        if not cached:
            cached = (
                db.query(DiscoveryCache)
                .filter(DiscoveryCache.ip_address == ip)
                .order_by(DiscoveryCache.last_seen.desc())
                .first()
            )

        if cached:
            cached.ip_address = ip
            if mac:
                cached.mac_address = mac
            cached.hostname = hostname or cached.hostname
            cached.os_guess = os_guess if os_guess != "unknown" else cached.os_guess
            cached.detection_method = "audit_scan"
            cached.last_seen = now
            cached.open_ports_json = json.dumps(open_ports)
            cached.connection_methods_json = json.dumps(conn_methods)
        else:
            db.add(DiscoveryCache(
                ip_address=ip,
                mac_address=mac,
                hostname=hostname or target.hostname,
                os_guess=os_guess if os_guess != "unknown" else None,
                detection_method="audit_scan",
                confidence=50,
                open_ports_json=json.dumps(open_ports),
                connection_methods_json=json.dumps(conn_methods),
                first_seen=now,
                last_seen=now,
            ))

        db.commit()
        logger.info(
            "Discovery refresh for %s: %d open ports",
            ip, len(open_ports),
        )
    except Exception:
        logger.warning("Discovery refresh failed for %s", ip, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass


def _decrypt_target_password(target: Target) -> str | None:
    """Decrypt the target's password if present."""
    if target.ssh_password_encrypted:
        try:
            return decrypt_value(target.ssh_password_encrypted, settings.SECRET_KEY)
        except Exception:
            logger.warning("Failed to decrypt password for target %s", target.id)
    return None


def _evaluate_result(
    result: CommandResult,
    expected_regex: str | None,
) -> tuple[str, str]:
    """Evaluate a command result and return a compliance status and explanation.

    Uses a **three-tier** classification that mirrors the PowerShell audit
    template (``Test-ExecutionError`` → ``Test-NotConfigured`` → expression
    evaluation) so that network scans and USB-imported scans produce
    identical results.

    Returns a tuple of (status, explanation) where status is one of:
    PASS, FAIL, ERROR
    """
    stdout_text = result.stdout or ""
    stderr_text = result.stderr or ""
    combined_output = (stdout_text + "\n" + stderr_text).strip()
    output_text = stdout_text if stdout_text.strip() else stderr_text
    output_stripped = output_text.strip() if output_text else ""

    # ── Tier 0: Total failure — non-zero exit and no output at all ──
    if result.exit_code != 0 and not combined_output:
        return "ERROR", f"Command failed with exit code {result.exit_code}"

    # ── Tier 1: Execution error (bad command, access denied, etc.) → ERROR ──
    category = classify_output(combined_output)
    if category == "execution_error":
        # Only evaluate against stdout if stdout itself is clean (no error markers).
        # This prevents false positives from extracting numbers out of error text
        # like "At line:1 char:2" matching expressions like "==1".
        if expected_regex and stdout_text.strip() and not is_execution_error(stdout_text):
            comp_result = evaluate_expression(expected_regex, stdout_text)
            if comp_result.matched:
                return "PASS", f"Evaluated from clean stdout despite stderr errors: {comp_result.explanation}"
            return "FAIL", f"Evaluated from clean stdout despite stderr errors: {comp_result.explanation}"
        return "ERROR", "Command execution error detected in output"

    # ── Tier 2: Not configured (missing registry key / GPO path) → FAIL ──
    # Evaluate with empty string so the comparison engine doesn't extract
    # numbers from the error message text.
    if category == "not_configured":
        if "no such file or directory" in combined_output.lower():
            return "FAIL", "Required file/path missing on target"
        if expected_regex:
            comp_result = evaluate_expression(expected_regex, "")
            if comp_result.matched:
                return "PASS", f"Not Configured - but expression matched empty: {comp_result.explanation}"
            return "FAIL", "Not Configured (registry key/GPO path missing)"
        return "FAIL", "Not Configured (registry key/GPO path missing)"

    # ── Tier 2b: Service not found → treat as Disabled ──
    if category == "service_not_found":
        if expected_regex:
            comp_result = evaluate_expression(expected_regex, "Disabled")
            if comp_result.matched:
                return "PASS", "Service not installed (treated as Disabled)"
            return "FAIL", "Service not installed"
        return "FAIL", "Service not installed"

    # ── Tier 2c: Module not found → module can't be loaded = secure ──
    # A kernel module that doesn't exist on disk is *more* secure than one
    # that is merely blacklisted via /bin/true.
    if category == "module_not_found":
        return "PASS", "Kernel module not found on system (equivalent to disabled)"

    # ── Tier 3: Normal evaluation via comparison engine ──
    # No expression to check — just confirm the command didn't error
    if not expected_regex:
        if result.exit_code != 0 and not (stdout_text.strip() if stdout_text else ""):
            return "ERROR", f"Command failed with exit code {result.exit_code}"
        if result.exit_code == 0:
            return "PASS", "Command executed successfully (no expected output defined)"
        return "FAIL", f"Command failed with exit code {result.exit_code}"

    # Evaluate using the comparison engine (handles >=, <=, ==, !=, contains:, regex:, and legacy regex)
    comp_result = evaluate_expression(expected_regex, output_text)
    if comp_result.matched:
        return "PASS", comp_result.explanation
    return "FAIL", comp_result.explanation


async def execute_network_scan(
    db_factory,
    scan_id: int,
    target_id: int,
    benchmark_id: int,
    selected_rule_ids: list[int] | None = None,
    category_filter: list[str] | None = None,
    severity_filter: list[str] | None = None,
    profile_filter: str | None = None,
    preset_id: int | None = None,
) -> None:
    """Run a full network scan asynchronously.

    This is the main entry point called from the API layer as a background task.
    It uses ``db_factory`` (a callable returning a new DB session) rather than
    accepting a session directly, because the scan runs in a background task.
    """
    db: Session = db_factory()
    connector: BaseConnector | None = None
    secondary_connector: BaseConnector | None = None

    try:
        # 1. Load scan, target, and rules
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        target = db.query(Target).filter(Target.id == target_id).first()
        benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()

        if not scan or not target:
            logger.error("Scan %s or target %s not found", scan_id, target_id)
            return

        # Parse connection_hints from the benchmark (if available)
        _connection_hints: dict[str, str] = {}
        if benchmark and benchmark.connection_hints:
            try:
                _connection_hints = json.loads(benchmark.connection_hints)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Invalid connection_hints JSON for benchmark %d",
                    benchmark_id,
                )

        # 2. Update scan to running
        scan.status = "running"
        scan.started_at = datetime.now(timezone.utc)
        db.commit()

        # 3. Decrypt credentials and attach to target
        target._decrypted_password = _decrypt_target_password(target)

        # 4. Get the right connector
        try:
            connector = get_connector(
                target.target_type, target.connection_method
            )
        except ValueError as exc:
            scan.status = "failed"
            scan.notes = str(exc)
            db.commit()
            return

        # 5. Connect
        try:
            await connector.connect(target)
        except (ConnectionError, ImportError) as exc:
            scan.status = "failed"
            scan.notes = f"Connection failed: {exc}"
            db.commit()
            return

        # 5b. Open secondary connector for dual-transport targets
        #     Uses connection_hints from the benchmark when available,
        #     falling back to the legacy hardcoded logic for older packs.
        target_type_lower = (target.target_type or "").lower()
        if _connection_hints:
            # Determine what transport the primary connector handles
            if target_type_lower in _DATABASE_TARGET_TYPES:
                primary_transport = "sql"
            elif target_type_lower in ("windows", "sharepoint"):
                primary_transport = "powershell"
            elif target_type_lower in ("cisco_ios", "cisco_asa", "juniper",
                                        "fortinet", "palo_alto", "arista",
                                        "hp_procurve", "checkpoint", "pfsense"):
                primary_transport = "cli"
            else:
                primary_transport = "shell"

            # Open a secondary connector for the first non-primary transport
            for transport_key, connector_name in _connection_hints.items():
                if transport_key != primary_transport:
                    try:
                        secondary_connector = get_connector(
                            target_type_lower,
                            connection_method=connector_name,
                        )
                        await secondary_connector.connect(target)
                        logger.info(
                            "Opened secondary %s connector for '%s' transport on %s",
                            connector_name, transport_key, target.ip_address,
                        )
                        break
                    except Exception as exc:
                        logger.warning(
                            "Secondary %s connector failed for %s: %s",
                            connector_name, target.ip_address, exc,
                        )
                        secondary_connector = None
        else:
            # Legacy fallback: hardcoded secondary connector logic
            if target_type_lower in _DATABASE_TARGET_TYPES:
                try:
                    secondary_connector = SSHConnector()
                    await secondary_connector.connect(target)
                    logger.info(
                        "Opened secondary SSH connector for database target %s",
                        target.ip_address,
                    )
                except Exception as exc:
                    logger.warning(
                        "Secondary SSH connector failed for %s (shell commands will use primary): %s",
                        target.ip_address, exc,
                    )
                    secondary_connector = None
            elif target_type_lower == "vmware_esxi":
                try:
                    secondary_connector = WinRMConnector()
                    await secondary_connector.connect(target)
                    logger.info(
                        "Opened secondary WinRM connector for ESXi target %s",
                        target.ip_address,
                    )
                except Exception as exc:
                    logger.warning(
                        "Secondary WinRM connector failed for %s (PowerCLI commands will be skipped): %s",
                        target.ip_address, exc,
                    )
                    secondary_connector = None

        # 6. Gather system info
        try:
            sys_info = await connector.get_system_info()
            target.os_details = json.dumps(sys_info)
            db.commit()
        except Exception as exc:
            logger.warning("Failed to collect system info: %s", exc)

        # 6b. Environment discovery — probe target for actual paths/config
        from backend.core.environment_discovery import discover_environment, adapt_command as adapt_cmd
        env_discovered: dict[str, str] = {}
        try:
            env_discovered = await discover_environment(
                connector, secondary_connector, target_type_lower,
                benchmark.platform if hasattr(benchmark, 'platform') else "",
            )
        except Exception as exc:
            logger.warning("Environment discovery failed: %s", exc)

        # 7. Build the list of rules to scan
        rules_query = (
            db.query(Rule)
            .filter(Rule.benchmark_id == benchmark_id, Rule.enabled.is_(True))
        )
        if selected_rule_ids:
            rules_query = rules_query.filter(Rule.id.in_(selected_rule_ids))
        if severity_filter:
            rules_query = rules_query.filter(Rule.severity.in_(severity_filter))
        if profile_filter:
            rules_query = rules_query.filter(
                Rule.profile_applicability.contains(profile_filter)
            )

        rules = rules_query.order_by(Rule.section_number).all()

        # If category filter, filter by tags
        if category_filter:
            filtered_rules = []
            for rule in rules:
                rule_tags = [t.tag_id for t in rule.tags] if rule.tags else []
                if any(cat in rule_tags for cat in category_filter):
                    filtered_rules.append(rule)
            rules = filtered_rules

        total = len(rules)

        # 8. Initialise progress tracker
        with _progress_lock:
            _scan_progress[scan_id] = {
                "scan_id": scan_id,
                "status": "running",
                "progress": 0,
                "total": total,
                "current_rule": "",
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "compliance_percentage": 0.0,
            }

        passed = failed = errors = 0
        consecutive_errors = 0

        # 9. Execute each rule
        for idx, rule in enumerate(rules):
            # Check for cancellation
            if scan_id in _cancelled_scans:
                scan.status = "cancelled"
                scan.notes = f"Cancelled after {idx} of {total} rules"
                break

            # Get the command for this rule
            cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule.id).first()
            if not cmd or not cmd.audit_command:
                continue
            if cmd.status in _SKIP_STATUSES:
                continue

            # Update progress
            with _progress_lock:
                _scan_progress[scan_id]["progress"] = idx + 1
                _scan_progress[scan_id]["current_rule"] = rule.section_number

            # Execute — route to the correct connector based on transport
            try:
                exec_cmd = cmd.audit_command

                # Adapt command with discovered environment values
                if env_discovered:
                    exec_cmd = adapt_cmd(exec_cmd, env_discovered)

                transport = cmd.command_transport or _infer_transport(
                    exec_cmd, target_type_lower
                )

                # Pick the right connector for this transport
                if transport == "shell" and secondary_connector:
                    chosen = secondary_connector
                elif transport == "powershell" and secondary_connector:
                    chosen = secondary_connector
                elif transport in ("sql",) and connector:
                    chosen = connector
                else:
                    chosen = connector

                # Auto-prefix sudo only for shell transport on Linux targets
                if transport == "shell" and target_type_lower in ("linux", "cassandra"):
                    exec_cmd = _prepare_linux_command(exec_cmd)

                result = await chosen.execute(exec_cmd, timeout=30)
                if result.exit_code == 0 or result.stdout.strip():
                    consecutive_errors = 0  # Reset on success
            except Exception as exc:
                result = CommandResult(
                    stdout="", stderr=str(exc), exit_code=-1, execution_time_ms=0
                )
                consecutive_errors += 1

            # Evaluate
            status, explanation = _evaluate_result(result, cmd.expected_output_regex)

            # Self-heal on ERROR: attempt to fix and re-execute once
            if status == "ERROR" and result.exit_code != 0:
                try:
                    from backend.core.self_healing import attempt_self_heal
                    healed = await attempt_self_heal(
                        rule_command=cmd,
                        error_output=result.stderr or result.stdout,
                        exit_code=result.exit_code,
                        connector=chosen,
                        db=db,
                    )
                    if healed and healed.get("corrected_command"):
                        retry_cmd = healed["corrected_command"]
                        retry_result = await chosen.execute(retry_cmd, timeout=30)
                        retry_expr = healed.get("corrected_expression") or cmd.expected_output_regex
                        retry_status, retry_expl = _evaluate_result(retry_result, retry_expr)
                        if retry_status != "ERROR":
                            result = retry_result
                            status = retry_status
                            explanation = f"[self-healed] {retry_expl}"
                except Exception as heal_exc:
                    logger.debug("Self-heal attempt failed: %s", heal_exc)

            if status == "PASS":
                passed += 1
                consecutive_errors = 0
            elif status == "FAIL":
                failed += 1
            else:
                errors += 1

            # Store finding
            finding = Finding(
                scan_id=scan_id,
                rule_id=rule.id,
                status=status,
                actual_output=result.stdout[:4000] if result.stdout else result.stderr[:4000],
                expected_output=cmd.expected_output_regex,
                severity=rule.severity,
                evaluation_explanation=explanation,
            )
            db.add(finding)
            db.commit()

            # Update running progress
            checked = passed + failed + errors
            pct = (passed / checked * 100) if checked > 0 else 0.0
            with _progress_lock:
                _scan_progress[scan_id].update(
                    {
                        "passed": passed,
                        "failed": failed,
                        "errors": errors,
                        "compliance_percentage": round(pct, 1),
                    }
                )

            # Abort if too many consecutive errors (likely connection issue)
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                scan.status = "failed"
                scan.notes = (
                    f"Aborted after {consecutive_errors} consecutive errors "
                    f"at rule {idx + 1}/{total}. Possible connection issue."
                )
                logger.error(
                    "Scan %s aborted: %d consecutive errors",
                    scan_id, consecutive_errors,
                )
                break

        # 10. Finalize scan
        if scan.status not in ("cancelled", "failed"):
            scan.status = "completed"
        scan.completed_at = datetime.now(timezone.utc)
        scan.total_rules = total
        scan.total_rules_checked = passed + failed + errors
        scan.passed = passed
        scan.failed = failed
        scan.errors = errors
        total_checked = passed + failed + errors
        scan.compliance_percentage = (
            round(passed / total_checked * 100, 1) if total_checked > 0 else 0.0
        )
        db.commit()

        logger.info(
            "Scan %s completed: %s/%s passed (%.1f%%)",
            scan_id,
            passed,
            total_checked,
            scan.compliance_percentage,
        )

        # 11. Refresh device discovery cache (ports / OS / connection methods)
        try:
            await _refresh_target_discovery(target, db)
        except Exception:
            logger.warning("Discovery refresh step failed for scan %s", scan_id, exc_info=True)

    except Exception as exc:
        logger.error("Scan %s failed with unexpected error: %s", scan_id, exc)
        try:
            scan = db.query(Scan).filter(Scan.id == scan_id).first()
            if scan:
                scan.status = "failed"
                scan.notes = f"Unexpected error: {exc}"
                scan.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass

    finally:
        # Clean up
        try:
            if secondary_connector:
                try:
                    await secondary_connector.disconnect()
                except Exception:
                    pass
            if connector:
                try:
                    await connector.disconnect()
                except Exception:
                    pass
        finally:
            with _progress_lock:
                _scan_progress.pop(scan_id, None)
                _cancelled_scans.discard(scan_id)
            db.close()
