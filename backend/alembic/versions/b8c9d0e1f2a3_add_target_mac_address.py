"""add mac_address to targets for persistent hardware identity

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-03-02

Adds mac_address column to targets table.  This allows the discovery
engine to tie a target to its hardware identifier (MAC address) so
that IP changes between audit sessions are automatically resolved.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column already exists (SQLite-safe)."""
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result)


def upgrade() -> None:
    if not _column_exists("targets", "mac_address"):
        op.add_column("targets", sa.Column("mac_address", sa.String(), nullable=True))
        op.create_index("ix_targets_mac_address", "targets", ["mac_address"])


def downgrade() -> None:
    op.drop_index("ix_targets_mac_address", table_name="targets")
    op.drop_column("targets", "mac_address")
