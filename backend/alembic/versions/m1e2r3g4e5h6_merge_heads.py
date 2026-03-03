"""Merge branch heads: b8c9d0e1f2a3 + h2i3j4k5l6m7.

Revision ID: m1e2r3g4e5h6
Revises: b8c9d0e1f2a3, h2i3j4k5l6m7
Create Date: 2026-03-03 19:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "m1e2r3g4e5h6"
down_revision = ("b8c9d0e1f2a3", "h2i3j4k5l6m7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
