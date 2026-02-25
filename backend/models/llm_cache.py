"""LLM response cache model — stores LLM responses keyed by a hash of the prompt."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from backend.database import Base


class LLMCache(Base):
    __tablename__ = "llm_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Cache key: SHA-256 hash of (system_prompt + prompt + model + task)
    cache_key = Column(String(64), nullable=False, unique=True, index=True)

    # Metadata for debugging / statistics
    task = Column(String(50))           # e.g. "phase2_commands", "phase1_parsing"
    model = Column(String(100))         # model name used
    prompt_preview = Column(String(200))  # first 200 chars of prompt for debugging

    # The cached response
    response_text = Column(Text, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    hit_count = Column(Integer, default=0)
