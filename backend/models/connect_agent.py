"""Connect agent model — tracks individual agent connections within a session."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class ConnectAgent(Base):
    __tablename__ = "connect_agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer, ForeignKey("connect_sessions.id", ondelete="CASCADE"), nullable=False
    )
    token = Column(String, unique=True, nullable=False, index=True)
    hostname = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    os_type = Column(String, nullable=True)  # windows / linux / darwin
    os_version = Column(String, nullable=True)
    status = Column(
        String, default="pending"
    )  # pending / connected / scanning / completed / disconnected
    connected_at = Column(DateTime, nullable=True)
    disconnected_at = Column(DateTime, nullable=True)
    target_id = Column(
        Integer, ForeignKey("targets.id", ondelete="SET NULL"), nullable=True
    )
    system_info = Column(Text, nullable=True)  # JSON blob

    session = relationship("ConnectSession", back_populates="agents")
    target = relationship("Target")
