from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from backend.database import Base


class VerificationReport(Base):
    __tablename__ = "verification_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_command_id = Column(Integer, ForeignKey("rule_commands.id", ondelete="CASCADE"), nullable=False)
    level = Column(String, nullable=False)
    result = Column(String, nullable=False)
    message = Column(Text)
    details = Column(Text)
    auto_fixable = Column(Boolean, default=False)
    run_at = Column(DateTime, default=datetime.utcnow)
