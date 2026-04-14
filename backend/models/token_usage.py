"""Token usage tracking — stores per-call token counts from LLM providers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String

from backend.database import Base


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # When this call happened
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Provider and model used
    provider = Column(String(50), nullable=False)   # "ollama", "openai", "anthropic", etc.
    model = Column(String(100), nullable=False)

    # Which pipeline task triggered this call (nullable for ad-hoc calls)
    task = Column(String(50), nullable=True)         # "phase2_commands", "copilot", etc.

    # Token counts
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
