"""Forge Trail — lightweight mission-scoped activity logging."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from backend.models.audit_log import AuditLog

logger = logging.getLogger("auditforge.trail")


def log_action(
    db: Session,
    *,
    user: Any | None = None,
    mission_id: int | None = None,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    entity_label: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Record an auditor action, optionally scoped to a mission.

    The caller is responsible for committing the session — this function
    only flushes so the row gets an ID. On failure, logging is isolated in
    nested transactions and downgraded to a best-effort compatibility insert
    for legacy schemas.
    """
    username = "system"
    user_id = None
    if user is not None:
        username = getattr(user, "username", "system")
        user_id = getattr(user, "id", None)

    entry = AuditLog(
        user_id=user_id,
        username=username,
        mission_id=mission_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        details_json=json.dumps(details) if details else None,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    try:
        # Isolate audit logging in a SAVEPOINT so schema drift or logging
        # failures never poison the caller's main transaction.
        with db.begin_nested():
            db.add(entry)
            db.flush()
    except Exception as exc:
        # Fallback for legacy DB schemas that may miss newer columns
        # (for example ip_address/user_agent). Insert only existing columns.
        try:
            bind = db.get_bind()
            cols = {c["name"] for c in inspect(bind).get_columns("audit_logs")}
            payload = {
                "user_id": user_id,
                "username": username,
                "mission_id": mission_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_label": entity_label,
                "details_json": json.dumps(details) if details else None,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "created_at": datetime.now(timezone.utc),
            }
            compat_payload = {k: v for k, v in payload.items() if k in cols}
            if not compat_payload:
                raise RuntimeError("audit_logs has no compatible columns")

            column_list = ", ".join(compat_payload.keys())
            value_list = ", ".join(f":{k}" for k in compat_payload)
            stmt = text(f"INSERT INTO audit_logs ({column_list}) VALUES ({value_list})")
            with db.begin_nested():
                db.execute(stmt, compat_payload)
        except Exception as fallback_exc:
            logger.warning(
                "Trail log_action flush failed (non-fatal): %s; fallback insert failed: %s",
                exc,
                fallback_exc,
            )
