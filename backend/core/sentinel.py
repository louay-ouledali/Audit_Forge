"""Forge Sentinel — scheduler engine and change detection."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.finding import Finding
from backend.models.rule import Rule
from backend.models.scan import Scan
from backend.models.schedule import Schedule
from backend.models.sentinel_run import SentinelRun
from backend.models.target import Target

logger = logging.getLogger("auditforge.sentinel")


def calculate_next_run(schedule: Schedule) -> datetime:
    """Compute the next run time based on schedule frequency and timezone."""
    try:
        tz = ZoneInfo(schedule.timezone) if schedule.timezone else timezone.utc
    except (KeyError, ValueError):
        tz = timezone.utc

    now = datetime.now(tz)
    try:
        hour, minute = (int(x) for x in schedule.time_of_day.split(":"))
    except (ValueError, AttributeError):
        hour, minute = 2, 0

    if schedule.frequency == "daily":
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    elif schedule.frequency == "weekly":
        dow = schedule.day_of_week or 0
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (dow - candidate.weekday()) % 7
        if days_ahead == 0 and candidate <= now:
            days_ahead = 7
        return (candidate + timedelta(days=days_ahead)).astimezone(timezone.utc)

    elif schedule.frequency == "monthly":
        dom = min(schedule.day_of_month or 1, 28)
        candidate = now.replace(day=dom, hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            if now.month == 12:
                candidate = candidate.replace(year=now.year + 1, month=1)
            else:
                candidate = candidate.replace(month=now.month + 1)
        return candidate.astimezone(timezone.utc)

    elif schedule.frequency == "custom":
        interval = schedule.custom_interval_hours or 24
        return (now + timedelta(hours=interval)).astimezone(timezone.utc)

    return (now + timedelta(days=1)).astimezone(timezone.utc)


def compare_runs(
    db: Session,
    current_scan_ids: list[int],
    previous_scan_ids: list[int],
) -> dict:
    """Compare findings between two sets of scans. Returns comparison results."""
    def _get_rule_status_map(scan_ids: list[int]) -> dict[str, dict]:
        """Build {rule_id: {status, severity, title, section}} from scan findings."""
        rows = (
            db.query(Finding, Rule)
            .outerjoin(Rule, Finding.rule_id == Rule.id)
            .filter(Finding.scan_id.in_(scan_ids))
            .all()
        )
        result = {}
        for f, r in rows:
            section = r.section_number if r else ""
            key = f"{f.rule_id}:{section}"
            result[key] = {
                "rule_id": f.rule_id,
                "rule_title": r.title if r else "Unknown",
                "rule_section": section,
                "status": f.status,
                "severity": f.severity or (r.severity if r else "medium") or "medium",
            }
        return result

    current = _get_rule_status_map(current_scan_ids)
    previous = _get_rule_status_map(previous_scan_ids)

    regressed = []
    improved = []
    critical_openings = []

    for key, cur in current.items():
        prev = previous.get(key)
        if prev and prev["status"] == "PASS" and cur["status"] == "FAIL":
            regressed.append({
                "rule_id": cur["rule_id"],
                "rule_title": cur["rule_title"],
                "section": cur["rule_section"],
                "severity": cur["severity"],
                "old": "PASS",
                "new": "FAIL",
            })
            if cur["severity"] in ("high", "critical"):
                critical_openings.append(cur)
        elif prev and prev["status"] == "FAIL" and cur["status"] == "PASS":
            improved.append({
                "rule_id": cur["rule_id"],
                "rule_title": cur["rule_title"],
                "section": cur["rule_section"],
                "severity": cur["severity"],
                "old": "FAIL",
                "new": "PASS",
            })

    # Compliance calculation
    total_current = len(current)
    pass_current = sum(1 for v in current.values() if v["status"] == "PASS")
    total_previous = len(previous)
    pass_previous = sum(1 for v in previous.values() if v["status"] == "PASS")

    compliance_current = (pass_current / total_current * 100) if total_current else 0
    compliance_previous = (pass_previous / total_previous * 100) if total_previous else 0

    return {
        "regressed": regressed,
        "improved": improved,
        "critical_openings": critical_openings,
        "compliance_current": round(compliance_current, 2),
        "compliance_previous": round(compliance_previous, 2),
        "compliance_delta": round(compliance_current - compliance_previous, 2),
        "rules_regressed": len(regressed),
        "rules_improved": len(improved),
        "critical_openings_count": len(critical_openings),
    }


def analyze_changes(comparison: dict, schedule: Schedule) -> list[dict]:
    """Determine which alerts should fire based on schedule thresholds."""
    alerts = []
    delta = comparison["compliance_delta"]
    threshold = schedule.regression_threshold or 5.0

    if schedule.notify_on_regression and delta < -threshold:
        alerts.append({
            "title": f"Compliance Regression: {abs(delta):.1f}% drop",
            "body": (
                f"Compliance dropped from {comparison['compliance_previous']:.1f}% to {comparison['compliance_current']:.1f}%. "
                f"{comparison['rules_regressed']} rules regressed, {comparison['rules_improved']} improved."
            ),
            "type": "critical" if delta < -10 else "warning",
            "icon": "trending-down",
        })

    if schedule.notify_on_critical and comparison["critical_openings_count"] > 0:
        names = ", ".join(c["rule_title"][:50] for c in comparison["critical_openings"][:3])
        alerts.append({
            "title": f"{comparison['critical_openings_count']} Critical/High Rule(s) Now Failing",
            "body": f"The following rules went from PASS → FAIL: {names}{'...' if comparison['critical_openings_count'] > 3 else ''}",
            "type": "critical",
            "icon": "shield-alert",
        })

    return alerts


def _target_has_credentials(target: Target) -> bool:
    """Check whether a target has any credentials configured."""
    return bool(
        target.ssh_password_encrypted
        or target.ssh_key_path
        or target.db_connection_string_encrypted
    )


async def execute_scheduled_run(db_factory, schedule_id: int) -> None:
    """Full lifecycle of one scheduled run."""
    from backend.core.scan_executor import execute_network_scan
    from backend.core.alert_dispatcher import dispatch_alerts

    db: Session = db_factory()
    run = None
    try:
        schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
        if not schedule:
            return

        target_ids = json.loads(schedule.target_ids_json or "[]")
        if not target_ids:
            logger.warning("Schedule %d has no targets", schedule_id)
            return

        # Create SentinelRun record
        run = SentinelRun(
            schedule_id=schedule_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()

        # Find previous scans for these targets in this mission
        previous_scan_ids = []
        if schedule.last_run_scan_ids_json:
            previous_scan_ids = json.loads(schedule.last_run_scan_ids_json)

        # Create scan rows for each target
        scan_ids = []
        skipped_targets = []
        scan_target_map: dict[int, int] = {}  # scan_id -> benchmark_id

        for tid in target_ids:
            target = db.query(Target).filter(Target.id == tid).first()
            if not target:
                continue

            # Check for benchmark
            if not target.default_benchmark_id:
                skipped_targets.append((target.hostname or target.ip_address or f"ID:{tid}", "no_benchmark"))
                logger.warning("Sentinel: target %d has no benchmark, skipping", tid)
                continue

            # Check for credentials
            if not _target_has_credentials(target):
                skipped_targets.append((target.hostname or target.ip_address or f"ID:{tid}", "no_credentials"))
                logger.warning("Sentinel: target %d has no credentials, skipping", tid)
                continue

            scan = Scan(
                target_id=tid,
                benchmark_id=target.default_benchmark_id,
                mission_id=schedule.mission_id,
                scan_mode="network",
                status="pending",
            )
            db.add(scan)
            db.flush()
            scan_ids.append(scan.id)
            scan_target_map[scan.id] = target.default_benchmark_id

        run.scan_ids_json = json.dumps(scan_ids)
        run.previous_scan_ids_json = json.dumps(previous_scan_ids)
        db.commit()

        # If no scannable targets, send failure alert and exit
        if not scan_ids:
            run.status = "failed"
            run.completed_at = datetime.now(timezone.utc)
            db.commit()

            # Send alert about why no scans could run
            reasons = "; ".join(f"{name} ({reason})" for name, reason in skipped_targets[:5])
            failure_alert = {
                "title": "Scheduled Scan Failed — No Scannable Targets",
                "body": f"All targets were skipped: {reasons}" if reasons else "No valid targets configured.",
                "type": "critical",
                "icon": "shield-alert",
            }
            try:
                sent = await dispatch_alerts(db, schedule=schedule, run=run, alerts=[failure_alert])
                run.alerts_sent_json = json.dumps(sent)
                db.commit()
            except Exception as alert_exc:
                logger.warning("Failed to dispatch failure alert: %s", alert_exc)
            return

        # Execute scans in dedicated threads (same pattern as batch scan API)
        # Each scan gets its own thread + event loop to avoid blocking the
        # main FastAPI event loop and to prevent thread-pool starvation.
        SCAN_TIMEOUT = 1800  # 30 minutes max per target
        scan_tasks = []  # (scan_id, target_id, benchmark_id) tuples

        def _run_one_scan_sync(sid: int, tid: int, bid: int) -> None:
            """Run one scan in a fresh event loop (blocking call)."""
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    execute_network_scan(
                        db_factory=db_factory,
                        scan_id=sid,
                        target_id=tid,
                        benchmark_id=bid,
                    )
                )
            except Exception as exc:
                logger.error("Sentinel scan %d crashed: %s", sid, exc)
                inner_db = db_factory()
                try:
                    s = inner_db.query(Scan).filter(Scan.id == sid).first()
                    if s and s.status in ("pending", "running"):
                        s.status = "failed"
                        s.notes = f"Scan crashed: {str(exc)[:300]}"
                        s.completed_at = datetime.now(timezone.utc)
                        inner_db.commit()
                finally:
                    inner_db.close()
            finally:
                loop.close()

        for sid in scan_ids:
            target_tid = None
            scan_row = db.query(Scan).filter(Scan.id == sid).first()
            if scan_row:
                target_tid = scan_row.target_id
            scan_tasks.append((sid, target_tid or 0, scan_target_map.get(sid, 0)))

        # Run all scans in parallel (each in its own thread)
        async_tasks = []
        for sid, tid, bid in scan_tasks:
            async_tasks.append(
                asyncio.wait_for(
                    asyncio.to_thread(_run_one_scan_sync, sid, tid, bid),
                    timeout=SCAN_TIMEOUT,
                )
            )

        results = await asyncio.gather(*async_tasks, return_exceptions=True)
        for (sid, _, _), result in zip(scan_tasks, results):
            if isinstance(result, asyncio.TimeoutError):
                logger.error("Sentinel scan %d timed out after %ds", sid, SCAN_TIMEOUT)
                err_db = db_factory()
                try:
                    s = err_db.query(Scan).filter(Scan.id == sid).first()
                    if s and s.status in ("pending", "running"):
                        s.status = "failed"
                        s.notes = f"Scan timed out after {SCAN_TIMEOUT}s"
                        s.completed_at = datetime.now(timezone.utc)
                        err_db.commit()
                finally:
                    err_db.close()
            elif isinstance(result, Exception):
                logger.error("Sentinel scan %d failed: %s", sid, result)

        # Refresh session to see changes made by execute_network_scan
        db.expire_all()

        # Check how many scans actually completed
        completed_count = 0
        failed_count = 0
        for sid in scan_ids:
            s = db.query(Scan).filter(Scan.id == sid).first()
            if s:
                if s.status == "completed":
                    completed_count += 1
                elif s.status == "failed":
                    failed_count += 1

        # Compare with previous run
        comparison = {}
        if previous_scan_ids and completed_count > 0:
            comparison = compare_runs(db, scan_ids, previous_scan_ids)
            run.compliance_current = comparison.get("compliance_current")
            run.compliance_previous = comparison.get("compliance_previous")
            run.compliance_delta = comparison.get("compliance_delta")
            run.rules_regressed = comparison.get("rules_regressed", 0)
            run.rules_improved = comparison.get("rules_improved", 0)
            run.critical_openings = comparison.get("critical_openings_count", 0)
            run.comparison_details_json = json.dumps(comparison)
        elif completed_count > 0:
            # First run — just compute current compliance
            total = db.query(Finding).filter(Finding.scan_id.in_(scan_ids)).count()
            passed = db.query(Finding).filter(
                Finding.scan_id.in_(scan_ids), Finding.status == "PASS"
            ).count()
            run.compliance_current = round((passed / total * 100) if total else 0, 2)

        # Analyze changes and dispatch alerts
        alerts_to_send: list[dict] = []

        # Always send a completion summary notification
        compliance_str = f"{run.compliance_current:.1f}%" if run.compliance_current is not None else "N/A"
        if completed_count > 0 and failed_count == 0:
            summary_body = f"Compliance: {compliance_str}"
            if comparison:
                delta = comparison.get("compliance_delta", 0)
                direction = "up" if delta > 0 else "down" if delta < 0 else "unchanged"
                summary_body += f" ({direction} {abs(delta):.1f}%)" if delta != 0 else " (unchanged)"
                summary_body += f" | {comparison.get('rules_regressed', 0)} regressed, {comparison.get('rules_improved', 0)} improved"
            alerts_to_send.append({
                "title": f"Scheduled Scan Completed — {schedule.name}",
                "body": f"{completed_count} target(s) scanned. {summary_body}",
                "type": "success",
                "icon": "check-circle",
            })
        elif completed_count > 0 and failed_count > 0:
            alerts_to_send.append({
                "title": f"Scheduled Scan Partially Completed — {schedule.name}",
                "body": f"{completed_count} succeeded, {failed_count} failed. Compliance: {compliance_str}",
                "type": "warning",
                "icon": "alert-triangle",
            })

        if comparison:
            alerts_to_send.extend(analyze_changes(comparison, schedule))

        # Send failure alert if any scans failed
        if failed_count > 0:
            fail_details = []
            for sid in scan_ids:
                s = db.query(Scan).filter(Scan.id == sid).first()
                if s and s.status == "failed":
                    t = db.query(Target).filter(Target.id == s.target_id).first()
                    tname = (t.hostname or t.ip_address) if t else f"Target #{s.target_id}"
                    reason = s.notes or "Unknown error"
                    fail_details.append(f"{tname}: {reason[:100]}")

            alerts_to_send.append({
                "title": f"Scheduled Scan: {failed_count}/{len(scan_ids)} Target(s) Failed",
                "body": "\n".join(fail_details[:5]),
                "type": "critical" if failed_count == len(scan_ids) else "warning",
                "icon": "shield-alert",
            })

        # Generate report if auto_generate_report is enabled
        report_attachment = None  # (filename, bytes, mime_type)
        report_download_url = None
        if schedule.auto_generate_report and completed_count > 0:
            try:
                from backend.core.report_generator import (
                    aggregate_report_data,
                    generate_excel_report,
                )
                from backend.config import PROJECT_ROOT

                report_data = aggregate_report_data("custom", None, scan_ids, db)
                fmt = schedule.report_format or "pdf"
                report_bytes = None
                ext = ""
                mime = ""

                if fmt == "pdf":
                    try:
                        from backend.core.report_generator import generate_pdf_report
                        report_bytes = generate_pdf_report(report_data, include_passed=True, db=db)
                        ext, mime = "pdf", "application/pdf"
                    except (OSError, ImportError) as pdf_exc:
                        logger.warning("PDF generation unavailable (%s), falling back to Excel", pdf_exc)
                        fmt = "excel"  # fall through to Excel below

                if fmt == "excel" or report_bytes is None:
                    report_bytes = generate_excel_report(report_data, include_passed=True)
                    ext, mime = "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

                filename = f"sentinel_{schedule_id}_run{run.id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.{ext}"

                # Save to disk for download link
                report_dir = PROJECT_ROOT / "data" / "sentinel_reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                (report_dir / filename).write_bytes(report_bytes)

                report_attachment = (filename, report_bytes, mime)
                report_download_url = f"/api/schedules/reports/{filename}"
                logger.info("Sentinel report generated: %s (%d bytes)", filename, len(report_bytes))
            except Exception as report_exc:
                logger.warning("Sentinel report generation failed: %s", report_exc)

        if alerts_to_send:
            try:
                sent = await dispatch_alerts(
                    db,
                    schedule=schedule,
                    run=run,
                    alerts=alerts_to_send,
                    report_attachment=report_attachment,
                    report_download_url=report_download_url,
                )
                run.alerts_sent_json = json.dumps(sent)
            except Exception as alert_exc:
                logger.warning("Failed to dispatch alerts: %s", alert_exc)

        # Update schedule
        schedule.last_run_at = datetime.now(timezone.utc)
        schedule.last_run_status = "completed" if completed_count > 0 else "failed"
        schedule.last_run_scan_ids_json = json.dumps(scan_ids)
        schedule.last_compliance = run.compliance_current
        schedule.next_run_at = calculate_next_run(schedule)

        run.status = "completed" if completed_count > 0 else "failed"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Sentinel run %d completed for schedule %d (%d ok, %d failed)",
                     run.id, schedule_id, completed_count, failed_count)

    except Exception as exc:
        logger.error("Sentinel run failed for schedule %d: %s", schedule_id, exc)
        try:
            if run:
                run.status = "failed"
                run.completed_at = datetime.now(timezone.utc)
                db.commit()
            else:
                db.rollback()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        db.close()


_running_schedules: set[int] = set()
_schedule_lock = asyncio.Lock()


async def _guarded_run(db_factory, schedule_id: int) -> None:
    """Execute a scheduled run with concurrency guard."""
    try:
        await execute_scheduled_run(db_factory, schedule_id)
    finally:
        async with _schedule_lock:
            _running_schedules.discard(schedule_id)


async def sentinel_loop(db_factory) -> None:
    """Background task: check every 60 seconds for due schedules."""
    while True:
        await asyncio.sleep(60)
        db = None
        try:
            db = db_factory()
            now = datetime.now(timezone.utc)
            due = (
                db.query(Schedule)
                .filter(Schedule.enabled == True, Schedule.next_run_at <= now)
                .all()
            )
            for schedule in due:
                async with _schedule_lock:
                    if schedule.id in _running_schedules:
                        logger.info("Sentinel: schedule %d already running, skipping", schedule.id)
                        continue
                    _running_schedules.add(schedule.id)
                logger.info("Sentinel: triggering schedule %d (%s)", schedule.id, schedule.name)
                asyncio.create_task(_guarded_run(db_factory, schedule.id))
        except Exception as exc:
            logger.warning("Sentinel loop error (non-fatal): %s", exc)
        finally:
            if db:
                db.close()
