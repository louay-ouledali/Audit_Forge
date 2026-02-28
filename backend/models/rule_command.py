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

    # Phase 3: LLM validation results (optional)
    validation_status = Column(String)  # null=not validated, validated/corrected/flagged
    validation_confidence = Column(String)  # null, high/medium/low
    validation_corrections = Column(Text)  # JSON array of {field, old_value, new_value, reason}
    validation_notes = Column(Text)
    validated_at = Column(DateTime)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime)

    # ── Pre-loaded benchmark intelligence fields ──
    empty_output_interpretation = Column(Text, nullable=True)   # What empty output means for this rule
    output_value_map_json = Column(Text, nullable=True)         # JSON dict: common value → meaning
    fp_conditions_json = Column(Text, nullable=True)            # JSON array of FP condition objects
    remediation_gpo_path = Column(Text, nullable=True)          # GPO navigation path (Windows rules)
    remediation_risk = Column(String, nullable=True)            # "low" / "medium" / "high"
    safe_to_automate = Column(Boolean, nullable=True, default=False)  # Can remediation be auto-applied?
    requires_restart = Column(Boolean, nullable=True, default=False)  # Does remediation need a reboot?

    rule = relationship("Rule", back_populates="commands")
