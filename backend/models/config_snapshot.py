from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class ConfigSnapshot(Base):
    __tablename__ = "config_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_id = Column(Integer, ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_id = Column(Integer, ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)
    source = Column(String, nullable=False)  # "auto_pull" | "upload" | "agent_push"
    config_format = Column(String, nullable=True)  # "ios" | "fortios" | "junos" | "panos_xml" | "pfsense_xml" | "checkpoint" | "unknown"
    raw_config = Column(Text, nullable=False)
    config_hash = Column(String, nullable=False)  # SHA-256 for dedup / change detection
    device_hostname = Column(String, nullable=True)
    platform_detected = Column(String, nullable=True)
    line_count = Column(Integer, nullable=True)
    snapshot_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    target = relationship("Target", back_populates="config_snapshots", foreign_keys=[target_id])
    scan = relationship("Scan", foreign_keys=[scan_id])
