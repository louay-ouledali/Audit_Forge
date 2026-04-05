from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from backend.database import Base


class SentinelRun(Base):
    __tablename__ = "sentinel_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_ids_json = Column(Text, nullable=False, default="[]")
    previous_scan_ids_json = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="running")
    compliance_current = Column(Float, nullable=True)
    compliance_previous = Column(Float, nullable=True)
    compliance_delta = Column(Float, nullable=True)
    rules_regressed = Column(Integer, default=0)
    rules_improved = Column(Integer, default=0)
    critical_openings = Column(Integer, default=0)
    comparison_details_json = Column(Text, nullable=True)
    report_id = Column(Integer, nullable=True)
    alerts_sent_json = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
