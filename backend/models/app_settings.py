from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Text

from backend.database import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    key = Column(Text, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)
