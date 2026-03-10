from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.database import Base


class BenchmarkGroup(Base):
    """Groups multiple versions of the same benchmark for the same platform.

    Example: CIS Windows 11 Enterprise v1.0.0 and v2.0.0 share a group with
    canonical_name="CIS Windows 11 Enterprise", platform="Windows 11 Enterprise".
    """

    __tablename__ = "benchmark_groups"
    __table_args__ = (UniqueConstraint("canonical_name", "platform"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(String, nullable=False)       # e.g. "CIS Windows 11 Enterprise"
    platform = Column(String, nullable=False)             # exact platform, e.g. "Windows 11 Enterprise"
    platform_family = Column(String, nullable=False)      # e.g. "Windows"
    framework = Column(String, nullable=False, default="cis")  # cis/nist/iso/stig/disa/custom/unknown
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    benchmarks = relationship("Benchmark", back_populates="group", foreign_keys="[Benchmark.group_id]")
