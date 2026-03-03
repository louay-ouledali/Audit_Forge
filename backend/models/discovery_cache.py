"""Discovery cache — stores historical device discovery results.

Each row represents the last-seen state of a host on a given subnet.
Updated on every discovery scan via upsert (MAC-first, fallback to IP).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from backend.database import Base


class DiscoveryCache(Base):
    __tablename__ = "discovery_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Network identity
    ip_address = Column(String(45), nullable=False, index=True)
    mac_address = Column(String(17), nullable=True, index=True)
    subnet = Column(String(50), nullable=True, index=True)

    # Host metadata (mirroring DiscoveredHost fields)
    hostname = Column(String(255), nullable=True)
    os_guess = Column(String(50), nullable=True)
    os_version = Column(String(255), nullable=True)
    vendor = Column(String(255), nullable=True)
    device_model = Column(String(255), nullable=True)
    firmware = Column(String(255), nullable=True)
    domain = Column(String(255), nullable=True)
    detection_method = Column(String(255), nullable=True)
    confidence = Column(Integer, default=0)

    # Serialized fields
    open_ports_json = Column(Text, nullable=True)     # JSON array of port objects
    connection_methods_json = Column(Text, nullable=True)  # JSON array of strings

    # Timestamps
    first_seen = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Composite index for fast upsert lookups
    __table_args__ = (
        Index("ix_discovery_cache_mac_subnet", "mac_address", "subnet"),
    )

    # ── Helpers ────────────────────────────────────────────

    @property
    def open_ports(self) -> list[dict]:
        if not self.open_ports_json:
            return []
        try:
            return json.loads(self.open_ports_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @open_ports.setter
    def open_ports(self, value: list[dict]) -> None:
        self.open_ports_json = json.dumps(value) if value else None

    @property
    def connection_methods(self) -> list[str]:
        if not self.connection_methods_json:
            return []
        try:
            return json.loads(self.connection_methods_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @connection_methods.setter
    def connection_methods(self, value: list[str]) -> None:
        self.connection_methods_json = json.dumps(value) if value else None

    def to_history_dict(self) -> dict:
        """Return a dict suitable for enriching discovery API responses."""
        return {
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }

    def __repr__(self) -> str:
        return (
            f"<DiscoveryCache(id={self.id}, ip={self.ip_address!r}, "
            f"mac={self.mac_address!r}, vendor={self.vendor!r})>"
        )
