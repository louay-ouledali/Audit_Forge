from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from backend.database import Base


class ScanPreset(Base):
    __tablename__ = "scan_presets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    benchmark_id = Column(Integer, ForeignKey("benchmarks.id"))
    selection_criteria = Column(Text, nullable=False)
    rule_count = Column(Integer)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
