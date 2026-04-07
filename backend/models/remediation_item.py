from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class RemediationItem(Base):
    __tablename__ = "remediation_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("remediation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    finding_id = Column(Integer, ForeignKey("findings.id", ondelete="SET NULL"), nullable=True)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="SET NULL"), nullable=True)

    section_number = Column(String, nullable=False)
    rule_title = Column(String, nullable=False)
    severity = Column(String, nullable=True)

    remediation_command = Column(Text, nullable=True)
    command_source = Column(String, nullable=False, default="benchmark")
    # benchmark | cis_text | auditor_edit
    command_transport = Column(String, nullable=True)
    # shell | powershell | sql | cli

    selected = Column(Boolean, default=True)
    status = Column(String, nullable=False, default="pending")
    # pending | executing | success | failed | skipped

    execution_output = Column(Text, nullable=True)
    execution_error = Column(Text, nullable=True)
    executed_at = Column(DateTime, nullable=True)

    order_index = Column(Integer, default=0)
    requires_privilege = Column(Boolean, default=False)

    session = relationship("RemediationSession", back_populates="items")
