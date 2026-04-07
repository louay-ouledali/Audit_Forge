from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship

from backend.database import Base


class RemediationSession(Base):
    __tablename__ = "remediation_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mission_id = Column(Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id = Column(Integer, ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(String, nullable=False, default="system")

    status = Column(String, nullable=False, default="draft")
    # draft | executing | completed | failed | exported
    execution_mode = Column(String, nullable=True)
    # network | airgap | agent

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    executed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    total_items = Column(Integer, default=0)
    succeeded_items = Column(Integer, default=0)
    failed_items = Column(Integer, default=0)
    skipped_items = Column(Integer, default=0)

    notes = Column(Text, nullable=True)
    scan_ids_json = Column(Text, nullable=True)  # JSON array of scan IDs used

    items = relationship("RemediationItem", back_populates="session", cascade="all, delete-orphan")
    mission = relationship("Mission")
    target = relationship("Target")
