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

    # ── Smart Import provenance ──
    source = Column(String, nullable=True)                # "cis_extract", "nessus_import", "manual", null
    framework_mappings = Column(Text, nullable=True)      # JSON: {"NIST_800_53": ["AC-3"], "HIPAA": ["164.306"], ...}
    framework_ref = Column(String, nullable=True)         # Original framework reference ID (e.g. NIST "AC-2", STIG "V-253283")

    # ── Pre-loaded benchmark intelligence fields ──
    narrative_group = Column(String, nullable=True)       # Key into report_profile.narrative_groups
    security_themes_json = Column(Text, nullable=True)    # JSON array of theme strings
    attack_chain_tags_json = Column(Text, nullable=True)  # JSON array of attack chain identifiers
    mitre_attack_json = Column(Text, nullable=True)       # JSON array of MITRE ATT&CK technique IDs
    risk_weight = Column(Integer, nullable=True, default=5)  # 1-10 risk weight for scoring
    related_rules_json = Column(Text, nullable=True)      # JSON array of related section numbers
    group_with_json = Column(Text, nullable=True)         # JSON array of section numbers to co-group

    benchmark = relationship("Benchmark", back_populates="rules")
    commands = relationship("RuleCommand", back_populates="rule", cascade="all, delete-orphan", uselist=False)
    tags = relationship("RuleTag", back_populates="rule", cascade="all, delete-orphan")
