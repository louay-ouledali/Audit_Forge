"""Add connection_hints column to benchmarks table.

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
Create Date: 2026-03-27

Stores JSON mapping of transport type -> connector name for dynamic
connector routing in the scan executor.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "s3t4u5v6w7x8"
down_revision = "r2s3t4u5v6w7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("benchmarks") as batch_op:
        batch_op.add_column(
            sa.Column("connection_hints", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("benchmarks") as batch_op:
        batch_op.drop_column("connection_hints")
