from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class Finding(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(Integer, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="SET NULL"), nullable=True)

    status = Column(String, nullable=False)
    actual_output = Column(Text)
    expected_output = Column(Text)
    severity = Column(String)
    evaluation_explanation = Column(Text)  # Human-readable explanation of the comparison result

    # ── Import provenance (source-agnostic, 2 columns) ──────
    import_source = Column(String, nullable=True)      # "nessus", "qualys", "native", null
    import_metadata = Column(Text, nullable=True)       # JSON blob: {plugin_id, source_row, ...}

    ai_advice = Column(Text)
    ai_advice_generated_at = Column(DateTime)

    auditor_notes = Column(Text)
    auditor_override = Column(String)  # confirmed / false_positive / accepted_risk

    # ── Auditor override fields ──────────────────────────
    auditor_status_override = Column(String, nullable=True)    # PASS / FAIL / N/A
    auditor_severity_override = Column(String, nullable=True)  # critical / high / medium / low
    auditor_description = Column(Text, nullable=True)
    auditor_remediation = Column(Text, nullable=True)
    override_reason = Column(Text, nullable=True)
    overridden_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    scan = relationship("Scan", back_populates="findings")
