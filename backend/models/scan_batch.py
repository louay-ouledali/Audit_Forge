"""ScanBatch and ScanBatchItem models for bulk "Scan All" operations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class ScanBatch(Base):
    """A batch of scans launched together via "Scan All"."""

    __tablename__ = "scan_batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mission_id = Column(
        Integer,
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String, default="pending")  # pending | running | completed | cancelled | partial
    total_targets = Column(Integer, default=0)
    completed_targets = Column(Integer, default=0)
    failed_targets = Column(Integer, default=0)
    skipped_targets = Column(Integer, default=0)
    concurrency = Column(Integer, default=3)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    mission = relationship("Mission")
    items = relationship(
        "ScanBatchItem",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ScanBatchItem.id",
    )


class ScanBatchItem(Base):
    """A single target within a scan batch."""

    __tablename__ = "scan_batch_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(
        Integer,
        ForeignKey("scan_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id = Column(
        Integer,
        ForeignKey("targets.id", ondelete="CASCADE"),
        nullable=False,
    )
    benchmark_id = Column(
        Integer,
        ForeignKey("benchmarks.id", ondelete="SET NULL"),
        nullable=True,
    )
    scan_id = Column(
        Integer,
        ForeignKey("scans.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String, default="pending")  # pending | running | completed | failed | skipped
    skip_reason = Column(String, nullable=True)  # no_credentials | no_benchmark | unreachable | usb_only
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    batch = relationship("ScanBatch", back_populates="items")
    target = relationship("Target")
    benchmark = relationship("Benchmark")
    scan = relationship("Scan")
