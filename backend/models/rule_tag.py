from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.database import Base


class RuleTag(Base):
    __tablename__ = "rule_tags"
    __table_args__ = (UniqueConstraint("rule_id", "tag_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="CASCADE"), nullable=False)
    tag_id = Column(String, nullable=False)
    source = Column(String, default="auto")

    rule = relationship("Rule", back_populates="tags")
