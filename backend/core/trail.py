"""Forge Trail — lightweight mission-scoped activity logging."""
from __future__ import annotations

import json
import logging
from typing import Any

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
    only flushes so the row gets an ID.  On failure the entry is expunged
    from the session (non-destructive to the caller's transaction).
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
        db.add(entry)
        db.flush()
    except Exception as exc:
        logger.warning("Trail log_action flush failed (non-fatal): %s", exc)
        try:
            db.expunge(entry)
        except Exception:
            pass
