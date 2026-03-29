from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_id = Column(Integer, ForeignKey("targets.id", ondelete="CASCADE"), nullable=False)
    benchmark_id = Column(Integer, ForeignKey("benchmarks.id", ondelete="SET NULL"), nullable=True)
    # Direct link to mission (since targets now belong to clients)
    mission_id = Column(Integer, ForeignKey("missions.id", ondelete="SET NULL"), nullable=True, index=True)
    scan_mode = Column(String, nullable=False)
    preset_id = Column(Integer, ForeignKey("scan_presets.id", ondelete="SET NULL"))

    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    status = Column(String, default="pending")

    total_rules = Column(Integer, default=0)
    total_rules_checked = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    not_applicable = Column(Integer, default=0)
    manual_review = Column(Integer, default=0)
    compliance_percentage = Column(Float)

    script_generated_at = Column(DateTime)
    results_imported_at = Column(DateTime)

    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    target = relationship("Target", back_populates="scans")
    mission = relationship("Mission", back_populates="scans")
    findings = relationship("Finding", back_populates="scan", cascade="all, delete-orphan")
