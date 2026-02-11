from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class MissionAnalysis(Base):
    __tablename__ = "mission_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mission_id = Column(Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False)
    analysis_type = Column(String, nullable=False)  # "cross_target", "cross_mission", "category_analysis"
    compared_mission_id = Column(Integer, ForeignKey("missions.id"), nullable=True)
    result_json = Column(Text, nullable=False)
    llm_model_used = Column(String)
    generated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    mission = relationship("Mission", back_populates="analyses", foreign_keys=[mission_id])
