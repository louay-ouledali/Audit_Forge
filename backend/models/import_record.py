"""ImportRecord model — audit trail for every Smart Import operation."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class ImportRecord(Base):
    __tablename__ = "import_records"

    id = Column(Integer, primary_key=True, autoincrement=True)

    scan_id = Column(Integer, ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)
    benchmark_id = Column(Integer, ForeignKey("benchmarks.id", ondelete="SET NULL"), nullable=True)
    target_id = Column(Integer, ForeignKey("targets.id", ondelete="SET NULL"), nullable=True)

    # Source file info
    source_filename = Column(String, nullable=True)
    source_format = Column(String, nullable=True)      # nessus_csv, nessus_html, auditforge_json
    source_tool = Column(String, nullable=True)         # nessus, qualys, native, etc.

    # Auto-detected metadata
    platform_detected = Column(String, nullable=True)   # Windows, Linux, etc.
    benchmark_detected = Column(String, nullable=True)   # Full benchmark name detected
    version_detected = Column(String, nullable=True)     # Benchmark version detected

    # Stats
    findings_imported = Column(Integer, default=0)

    # Full metadata blob for audit trail
    metadata_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
