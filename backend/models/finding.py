from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class Finding(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(Integer, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(Integer, ForeignKey("rules.id"), nullable=False)

    status = Column(String, nullable=False)
    actual_output = Column(Text)
    expected_output = Column(Text)
    severity = Column(String)

    ai_advice = Column(Text)
    ai_advice_generated_at = Column(DateTime)

    auditor_notes = Column(Text)
    auditor_override = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)

    scan = relationship("Scan", back_populates="findings")
