from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class MissionTopology(Base):
    __tablename__ = "mission_topology"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mission_id = Column(Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, unique=True)
    graph_json = Column(Text, nullable=False)  # {nodes: [...], edges: [...]}
    auto_layout_json = Column(Text, nullable=True)
    user_layout_json = Column(Text, nullable=True)
    last_rebuilt_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    mission = relationship("Mission", back_populates="topology")
