from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from backend.database import Base


class CommandCache(Base):
    """Global cross-benchmark command registry.

    Stores audit/remediation commands keyed by normalised rule identity,
    decoupled from any single benchmark.  Enables cross-version and
    cross-framework command reuse with confidence scoring.
    """

    __tablename__ = "command_cache"
    __table_args__ = (
        UniqueConstraint("cache_key", "platform", name="uq_command_cache_key_platform"),
        Index("ix_command_cache_platform_section", "platform", "section_number"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identity
    cache_key = Column(String(64), nullable=False)        # SHA-256 of normalised rule identity
    platform = Column(String, nullable=False)             # exact, e.g. "Windows 11 Enterprise"
    platform_family = Column(String, nullable=False)
    section_number = Column(String, nullable=False)
    rule_title_normalized = Column(String, nullable=False) # lowercase, stripped, no profile markers

    # Command data
    audit_command = Column(Text)
    expected_output_regex = Column(Text)
    expected_output_description = Column(Text)
    remediation_command = Column(Text)
    remediation_description = Column(Text)

    # Provenance
    source_benchmark_id = Column(Integer, ForeignKey("benchmarks.id", ondelete="SET NULL"), nullable=True)
    source_framework = Column(String, default="cis")      # cis/nist/stig/iso/disa/custom

    # Confidence & matching
    confidence = Column(Float, nullable=False, default=1.0)  # 0.0 – 1.0
    match_type = Column(String, nullable=False, default="exact_version")  # exact_version/cross_version/cross_framework

    # Verification
    verification_status = Column(String, default="unverified")  # unverified/verified/flagged

    # Usage tracking
    hit_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, nullable=True)


#  Helpers (importable by command_cache_manager and elsewhere)

_STRIP_RE = re.compile(r"\(L[12]\)|\(NG\)|\(BL\)|[^\w\s]", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_ARTICLE_RE = re.compile(r"\b(the|a|an|and|or|of|to|for|in|on|is|are|be)\b", re.IGNORECASE)


def normalize_title(title: str) -> str:
    """Normalise a rule title for cache-key generation.

    Strips profile markers like (L1)/(L2)/(NG)/(BL), removes punctuation
    and articles, collapses whitespace, lowercases.
    """
    t = _STRIP_RE.sub(" ", title)
    t = _ARTICLE_RE.sub(" ", t)
    t = _SPACE_RE.sub(" ", t).strip().lower()
    return t


def make_cache_key(platform: str, section_number: str, rule_title: str) -> str:
    """Build the deterministic SHA-256 cache key for a rule."""
    parts = "|".join([
        platform.strip().lower(),
        section_number.strip(),
        normalize_title(rule_title),
    ])
    return hashlib.sha256(parts.encode()).hexdigest()
