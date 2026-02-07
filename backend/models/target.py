from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class Target(Base):
    __tablename__ = "targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mission_id = Column(Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False)
    hostname = Column(String)
    ip_address = Column(String)
    target_type = Column(String, nullable=False)
    os_details = Column(String)
    connection_method = Column(String)

    ssh_username = Column(String)
    ssh_key_path = Column(String)
    ssh_password_encrypted = Column(Text)
    port = Column(Integer)
    db_connection_string_encrypted = Column(Text)

    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    mission = relationship("Mission", back_populates="targets")
    scans = relationship("Scan", back_populates="target", cascade="all, delete-orphan")
