from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base

# Ensure BenchmarkGroup is importable for FK resolution
from backend.models.benchmark_group import BenchmarkGroup  # noqa: F401


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    platform = Column(String, nullable=False)
    platform_family = Column(String, nullable=False)
    import_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    pdf_filename = Column(String)
    pdf_hash = Column(String)
    total_rules = Column(Integer, default=0)
    phase1_status = Column(String, default="pending")
    phase2_status = Column(String, default="pending")
    verification_status = Column(String, default="pending")
    is_ready = Column(Boolean, default=False)
    status = Column(String, default="active")
    enrichment_stats = Column(Text)
    phase3_status = Column(String)  # null=never started, pending/processing/completed/failed/paused
    phase3_stats = Column(Text)  # JSON: {total, processed, validated, corrected, flagged}
    notes = Column(Text)

    # ── Pre-loaded benchmark fields ──
    source = Column(String, default="user_imported")  # "preloaded" or "user_imported"
    preloaded_version = Column(String, nullable=True)  # Pack version for upgrade tracking
    pack_hash = Column(String, nullable=True)  # SHA-256 of the .auditforge.json file

    # ── Smart Import / Benchmark Studio fields ──
    is_editable = Column(Boolean, default=False)         # True for reconstructed/custom benchmarks
    parent_benchmark_id = Column(Integer, ForeignKey("benchmarks.id", ondelete="SET NULL"), nullable=True)
    migration_readiness = Column(Float, nullable=True)   # % of rules with validated commands
    source_details = Column(Text, nullable=True)         # JSON: {import_source, auto_detected, platform_info}

    # ── Version grouping & multi-framework fields ──
    group_id = Column(Integer, ForeignKey("benchmark_groups.id", ondelete="SET NULL"), nullable=True)
    framework = Column(String, default="cis")            # cis/nist/iso/stig/disa/custom/unknown
    is_baseline = Column(Boolean, default=False)         # Primary version in a group for comparison

    group = relationship("BenchmarkGroup", back_populates="benchmarks", foreign_keys=[group_id])
    rules = relationship("Rule", back_populates="benchmark", cascade="all, delete-orphan",
                         foreign_keys="[Rule.benchmark_id]")
