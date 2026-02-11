from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (UniqueConstraint("benchmark_id", "section_number"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    benchmark_id = Column(Integer, ForeignKey("benchmarks.id", ondelete="CASCADE"), nullable=False)
    section_number = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    rationale = Column(Text)
    profile_applicability = Column(Text)
    assessment_type = Column(String)
    default_value = Column(Text)
    references_json = Column(Text)
    cis_controls = Column(Text)
    audit_description_raw = Column(Text)
    remediation_description_raw = Column(Text)
    severity = Column(String, default="medium")
    enabled = Column(Boolean, default=True)

    benchmark = relationship("Benchmark", back_populates="rules")
    commands = relationship("RuleCommand", back_populates="rule", cascade="all, delete-orphan", uselist=False)
    tags = relationship("RuleTag", back_populates="rule", cascade="all, delete-orphan")
