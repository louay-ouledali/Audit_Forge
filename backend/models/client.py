from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    industry = Column(String)
    contact_name = Column(String)
    contact_email = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    missions = relationship("Mission", back_populates="client", cascade="all, delete-orphan")
