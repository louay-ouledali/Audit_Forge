from __future__ import annotations

import difflib
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from backend.connectors import get_connector
from backend.core.config_audit.detect import detect_config_format
from backend.core.config_audit.parsers import get_parser
from backend.core.config_audit.puller import pull_config
from backend.database import get_db
from backend.models.config_snapshot import ConfigSnapshot
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.target import Target
from backend.schemas.config_snapshot import (
    ConfigCoverageResponse,
    ConfigDiffResponse,
    ConfigSnapshotDetail,
    ConfigSnapshotResponse,
    ConfigUpload,
    SecurityFindingResponse,
)
from backend.utils.encryption import decrypt_value
from backend.config import settings

router = APIRouter(tags=["configs"])
logger = logging.getLogger("auditforge.api.configs")


def _build_snapshot(
    target: Target,
    raw_config: str,
    source: str,
    scan_id: int | None = None,
) -> ConfigSnapshot:
    """Detect format, parse, and build a ConfigSnapshot (not yet flushed)."""
    config_format = detect_config_format(raw_config)
    parser = get_parser(config_format)
    parsed = parser.parse(raw_config)

    return ConfigSnapshot(
        target_id=target.id,
        scan_id=scan_id,
        source=source,
        config_format=config_format,
        raw_config=raw_config,
        config_hash=hashlib.sha256(raw_config.encode()).hexdigest(),
        device_hostname=parsed.hostname,
        platform_detected=config_format if config_format != "unknown" else None,
        line_count=len(raw_config.splitlines()),
        snapshot_at=datetime.now(timezone.utc),
    )


def _get_target_or_404(target_id: int, db: Session) -> Target:
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    return target


def _get_snapshot_or_404(snapshot_id: int, db: Session) -> ConfigSnapshot:
    snap = db.query(ConfigSnapshot).filter(ConfigSnapshot.id == snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Config snapshot not found")
    return snap


# Target-scoped endpoints


@router.post(
    "/targets/{target_id}/configs/upload",
    response_model=ConfigSnapshotResponse,
    status_code=201,
)
def upload_config(
    target_id: int,
    payload: ConfigUpload,
    db: Session = Depends(get_db),
):
    """Upload raw configuration text and create a snapshot."""
    target = _get_target_or_404(target_id, db)

    snap = _build_snapshot(target, payload.raw_config, source=payload.source)
    db.add(snap)
    db.flush()

    target.latest_config_id = snap.id
    db.commit()
    db.refresh(snap)
    return snap


@router.post(
    "/targets/{target_id}/configs/pull",
    response_model=ConfigSnapshotResponse,
    status_code=201,
)
async def pull_config_endpoint(
    target_id: int,
    db: Session = Depends(get_db),
):
    """Pull running config from a live device and save a snapshot."""
    target = _get_target_or_404(target_id, db)

    try:
        connector = get_connector(target.target_type, target.connection_method)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"No connector available: {exc}")

    # Attach decrypted password for connector auth
    if target.ssh_password_encrypted:
        try:
            target._decrypted_password = decrypt_value(
                target.ssh_password_encrypted, settings.effective_encryption_key
            )
        except Exception:
            target._decrypted_password = None

    try:
        await connector.connect(target)
        raw_config, _cmd = await pull_config(connector, target.target_type)
        await connector.disconnect()
    except Exception as exc:
        try:
            await connector.disconnect()
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=f"Config pull failed: {exc}")

    snap = _build_snapshot(target, raw_config, source="auto_pull")
    db.add(snap)
    db.flush()

    target.latest_config_id = snap.id
    db.commit()
    db.refresh(snap)
    return snap


@router.get(
    "/targets/{target_id}/configs",
    response_model=list[ConfigSnapshotResponse],
)
def list_snapshots(
    target_id: int,
    db: Session = Depends(get_db),
):
    """List all config snapshots for a target, newest first."""
    _get_target_or_404(target_id, db)
    return (
        db.query(ConfigSnapshot)
        .filter(ConfigSnapshot.target_id == target_id)
        .order_by(ConfigSnapshot.snapshot_at.desc())
        .all()
    )


@router.get(
    "/targets/{target_id}/configs/latest",
    response_model=ConfigSnapshotResponse,
)
def latest_snapshot(
    target_id: int,
    db: Session = Depends(get_db),
):
    """Return the most recent config snapshot for a target."""
    _get_target_or_404(target_id, db)
    snap = (
        db.query(ConfigSnapshot)
        .filter(ConfigSnapshot.target_id == target_id)
        .order_by(ConfigSnapshot.snapshot_at.desc())
        .first()
    )
    if not snap:
        raise HTTPException(status_code=404, detail="No config snapshots for this target")
    return snap


# Snapshot-scoped endpoints


@router.get("/configs/{snapshot_id}", response_model=ConfigSnapshotDetail)
def get_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    """Get full snapshot detail including raw config."""
    return _get_snapshot_or_404(snapshot_id, db)


@router.get("/configs/{snapshot_id}/diff/{other_id}", response_model=ConfigDiffResponse)
def diff_snapshots(
    snapshot_id: int,
    other_id: int,
    db: Session = Depends(get_db),
):
    """Compute a unified diff between two config snapshots."""
    snap_a = _get_snapshot_or_404(snapshot_id, db)
    snap_b = _get_snapshot_or_404(other_id, db)

    lines_a = snap_a.raw_config.splitlines(keepends=True)
    lines_b = snap_b.raw_config.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=f"snapshot-{snap_a.id}",
            tofile=f"snapshot-{snap_b.id}",
        )
    )
    unified = "".join(diff_lines)
    added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

    return ConfigDiffResponse(
        snapshot_a_id=snap_a.id,
        snapshot_b_id=snap_b.id,
        unified_diff=unified,
        lines_added=added,
        lines_removed=removed,
    )


@router.get(
    "/configs/{snapshot_id}/security-checks",
    response_model=list[SecurityFindingResponse],
)
def security_checks(snapshot_id: int, db: Session = Depends(get_db)):
    """Run security checks against a parsed config."""
    from backend.core.config_audit.security_checks import run_security_checks

    snap = _get_snapshot_or_404(snapshot_id, db)
    findings = run_security_checks(snap.raw_config, snap.config_format or "unknown")
    return [
        SecurityFindingResponse(
            check_id=f.check_id,
            severity=f.severity,
            title=f.title,
            description=f.description,
            remediation=f.remediation,
            matched_lines=f.matched_lines,
        )
        for f in findings
    ]


@router.get(
    "/configs/{snapshot_id}/coverage/{benchmark_id}",
    response_model=ConfigCoverageResponse,
)
def config_coverage(
    snapshot_id: int,
    benchmark_id: int,
    db: Session = Depends(get_db),
):
    """Estimate how many benchmark rules can be answered from this config snapshot."""
    snap = _get_snapshot_or_404(snapshot_id, db)

    parser = get_parser(snap.config_format or "unknown")
    parsed = parser.parse(snap.raw_config)

    rule_commands = (
        db.query(RuleCommand)
        .join(Rule, Rule.id == RuleCommand.rule_id)
        .filter(Rule.benchmark_id == benchmark_id)
        .all()
    )

    total = len(rule_commands)
    answerable = 0
    unanswerable_cmds: list[str] = []

    for rc in rule_commands:
        cmd = rc.audit_command
        if not cmd:
            unanswerable_cmds.append(f"rule {rc.rule_id}: (no command)")
            continue
        try:
            result = parser.simulate(cmd, parsed)
            if result is not None:
                answerable += 1
            else:
                unanswerable_cmds.append(cmd)
        except Exception:
            unanswerable_cmds.append(cmd)

    unanswerable = total - answerable
    pct = (answerable / total * 100) if total else 0.0

    return ConfigCoverageResponse(
        total_rules=total,
        answerable=answerable,
        unanswerable=unanswerable,
        coverage_pct=round(pct, 2),
        unanswerable_commands=unanswerable_cmds,
    )


@router.delete("/configs/{snapshot_id}", status_code=204)
def delete_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    """Delete a config snapshot."""
    snap = _get_snapshot_or_404(snapshot_id, db)

    # Clear latest_config_id on target if it points to this snapshot
    target = db.query(Target).filter(Target.id == snap.target_id).first()
    if target and target.latest_config_id == snap.id:
        target.latest_config_id = None

    db.delete(snap)
    db.commit()
    return Response(status_code=204)
