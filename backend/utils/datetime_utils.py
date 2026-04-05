"""Shared datetime serialization utilities for AuditForge APIs."""
from __future__ import annotations

from datetime import datetime, timezone


def utc_iso(dt: datetime | None) -> str | None:
    """Serialize a (possibly naive-UTC) datetime with an explicit ``Z`` suffix.

    Backend stores UTC timestamps via ``datetime.now(timezone.utc)`` but
    SQLAlchemy's ``DateTime`` column strips tzinfo.  Without a trailing
    ``Z``, JavaScript's ``new Date()`` interprets the ISO string as
    **local time**, causing an offset equal to the user's UTC offset.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Naive → assume UTC
        return dt.isoformat() + "Z"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
