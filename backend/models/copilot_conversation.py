from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from backend.database import Base


class CopilotConversation(Base):
    __tablename__ = "copilot_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, unique=True, index=True, nullable=False)
    benchmark_id = Column(Integer, ForeignKey("benchmarks.id", ondelete="CASCADE"), nullable=False)
    messages_json = Column(Text, default="[]")  # JSON array of {role, content}
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
