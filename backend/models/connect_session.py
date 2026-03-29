"""Connect session model — tracks AuditForge Connect enrollment sessions."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class ConnectSession(Base):
    __tablename__ = "connect_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    enrollment_code = Column(String(8), unique=True, nullable=False, index=True)
    client_id = Column(
        Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    mission_id = Column(
        Integer, ForeignKey("missions.id", ondelete="SET NULL"), nullable=True
    )
    status = Column(String, default="active")  # active / expired / terminated
    created_by = Column(String, nullable=True)  # placeholder for future auth
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=False)
    max_agent_lifetime_seconds = Column(Integer, default=14400)  # 4 hours
    notes = Column(Text, nullable=True)

    client = relationship("Client", backref="connect_sessions")
    mission = relationship("Mission", backref="connect_sessions")
    agents = relationship(
        "ConnectAgent", back_populates="session", cascade="all, delete-orphan"
    )
