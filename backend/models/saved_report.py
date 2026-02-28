"""Saved / generated report model."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, LargeBinary, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class SavedReport(Base):
    __tablename__ = "saved_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mission_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Report configuration snapshot (JSON)
    scope = Column(String(50), nullable=True)          # scan / target / mission / custom
    scope_id = Column(Integer, nullable=True)
    scan_ids_json = Column(Text, nullable=True)        # JSON array of scan ids
    config_json = Column(Text, nullable=True)          # full builder config snapshot

    # Output
    format = Column(String(10), nullable=False, default="html")  # html / pdf
    generated_blob = Column(LargeBinary, nullable=True)
    file_size_kb = Column(Float, nullable=True)

    # AI enhancement
    ai_enhanced = Column(String(20), default="none")   # none / pending / completed / failed
    ai_enhanced_at = Column(DateTime, nullable=True)

    # Status
    status = Column(String(20), default="draft")       # draft / generated / finalized
    generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
