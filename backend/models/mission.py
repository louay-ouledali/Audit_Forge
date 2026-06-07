from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class Mission(Base):
    __tablename__ = "missions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    start_date = Column(Date)
    end_date = Column(Date)
    status = Column(String, default="in_progress")
    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Mission locking
    is_locked = Column(Boolean, default=False)
    password_hash = Column(String, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String, nullable=True)

    # Relationships
    client = relationship("Client", back_populates="missions")
    # Many-to-many with targets via junction table
    targets = relationship(
        "Target",
        secondary="mission_targets",
        back_populates="missions",
    )
    # Scans linked directly to mission
    scans = relationship("Scan", back_populates="mission", cascade="all, delete-orphan")
    analyses = relationship(
        "MissionAnalysis",
        back_populates="mission",
        cascade="all, delete-orphan",
        foreign_keys="MissionAnalysis.mission_id",
    )
    topology = relationship(
        "MissionTopology",
        back_populates="mission",
        uselist=False,
        cascade="all, delete-orphan",
    )
