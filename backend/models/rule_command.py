from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class RuleCommand(Base):
    __tablename__ = "rule_commands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, unique=True)

    audit_command = Column(Text)
    expected_output_regex = Column(Text)
    expected_output_description = Column(Text)
    remediation_command = Column(Text)
    remediation_description = Column(Text)

    status = Column(String, default="generated")
    source = Column(String, default="llm_generated")

    is_protected = Column(Boolean, default=False)
    protection_reason = Column(Text)
    protected_at = Column(DateTime)

    verified_at = Column(DateTime)
    verification_notes = Column(Text)

    flagged_at = Column(DateTime)
    flag_reason = Column(Text)
    flag_error_output = Column(Text)

    regeneration_count = Column(Integer, default=0)
    last_regenerated_at = Column(DateTime)
    previous_commands = Column(Text)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime)

    rule = relationship("Rule", back_populates="commands")
