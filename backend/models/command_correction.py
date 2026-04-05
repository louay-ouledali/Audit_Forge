"""CommandCorrection model — tracks self-healing fixes applied to commands."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class CommandCorrection(Base):
    __tablename__ = "command_corrections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_command_id = Column(
        Integer,
        ForeignKey("rule_commands.id", ondelete="CASCADE"),
        nullable=False,
    )

    # What failed
    original_command = Column(Text, nullable=False)
    original_expression = Column(Text, nullable=True)
    error_output = Column(Text, nullable=True)
    error_type = Column(String, nullable=True)  # timeout, syntax, no_output, permission, connection

    # What was fixed
    corrected_command = Column(Text, nullable=True)
    corrected_expression = Column(Text, nullable=True)
    correction_source = Column(String, nullable=False)  # llm_regen, pattern_fix, env_adapt, fallback
    correction_notes = Column(Text, nullable=True)

    # Outcome
    correction_worked = Column(Integer, nullable=True)  # 1=yes, 0=no, null=pending
    new_confidence = Column(Float, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    rule_command = relationship("RuleCommand")
