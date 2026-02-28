"""Junction table for many-to-many relationship between missions and targets."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Table

from backend.database import Base

# Association table – no ORM model needed for simple M2M,
# but we define a full model so Alembic picks it up and we can store `added_at`.


class MissionTarget(Base):
    __tablename__ = "mission_targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mission_id = Column(
        Integer,
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id = Column(
        Integer,
        ForeignKey("targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
