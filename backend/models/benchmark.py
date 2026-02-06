from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    platform = Column(String, nullable=False)
    platform_family = Column(String, nullable=False)
    import_date = Column(DateTime, default=datetime.utcnow)
    pdf_filename = Column(String)
    pdf_hash = Column(String)
    total_rules = Column(Integer, default=0)
    phase1_status = Column(String, default="pending")
    phase2_status = Column(String, default="pending")
    verification_status = Column(String, default="pending")
    is_ready = Column(Boolean, default=False)
    status = Column(String, default="active")
    enrichment_stats = Column(Text)
    notes = Column(Text)

    rules = relationship("Rule", back_populates="benchmark", cascade="all, delete-orphan")
