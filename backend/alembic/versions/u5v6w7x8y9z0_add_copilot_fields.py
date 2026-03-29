"""Add Forge Copilot fields to rules table.

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
Create Date: 2026-03-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "u5v6w7x8y9z0"
down_revision = "t4u5v6w7x8y9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rules") as batch_op:
        batch_op.add_column(sa.Column("pending_review", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("copilot_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("copilot_source_benchmark", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("rules") as batch_op:
        batch_op.drop_column("copilot_source_benchmark")
        batch_op.drop_column("copilot_confidence")
        batch_op.drop_column("pending_review")
