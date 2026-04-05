from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from backend.database import Base


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    mission_id = Column(Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    target_ids_json = Column(Text, nullable=False, default="[]")
    frequency = Column(String, nullable=False)  # daily | weekly | monthly | custom
    day_of_week = Column(Integer, nullable=True)  # 0=Mon..6=Sun
    day_of_month = Column(Integer, nullable=True)  # 1-28
    time_of_day = Column(String, nullable=False, default="02:00")
    custom_interval_hours = Column(Integer, nullable=True)
    timezone = Column(String, default="UTC")
    enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String, nullable=True)
    last_run_scan_ids_json = Column(Text, nullable=True)
    last_compliance = Column(Float, nullable=True)
    next_run_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    notify_on_regression = Column(Boolean, default=True)
    notify_on_critical = Column(Boolean, default=True)
    regression_threshold = Column(Float, default=5.0)
    alert_channels_json = Column(Text, default='["in_app"]')
    alert_emails = Column(Text, nullable=True)
    slack_webhook_url = Column(Text, nullable=True)
    auto_generate_report = Column(Boolean, default=False)
    report_format = Column(String, default="pdf")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=True)
