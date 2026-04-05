"""Add copilot_conversations table for persistent chat history.

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
Create Date: 2026-03-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "v6w7x8y9z0a1"
down_revision = "u5v6w7x8y9z0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = sa.inspect(conn).get_table_names()
    if "copilot_conversations" not in tables:
        op.create_table(
            "copilot_conversations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("conversation_id", sa.String(), nullable=False, unique=True, index=True),
            sa.Column("benchmark_id", sa.Integer(), sa.ForeignKey("benchmarks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("messages_json", sa.Text(), server_default="[]"),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )


def downgrade() -> None:
    op.drop_table("copilot_conversations")
