from __future__ import annotations

from datetime import datetime, timezone

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # ── Active Directory credentials ─────────────────────────
    ad_domain = Column(String, nullable=True)          # e.g. "corp.example.com"
    ad_dc_host = Column(String, nullable=True)         # DC hostname/IP
    ad_username = Column(String, nullable=True)        # DOMAIN\user or user@domain
    ad_password_encrypted = Column(Text, nullable=True) # Fernet-encrypted password
    ad_use_ssl = Column(Integer, nullable=True, default=1)  # 1=LDAPS, 0=LDAP
    ad_base_ou = Column(String, nullable=True)         # optional OU filter

    missions = relationship("Mission", back_populates="client", cascade="all, delete-orphan")
    targets = relationship("Target", back_populates="client", cascade="all, delete-orphan")
