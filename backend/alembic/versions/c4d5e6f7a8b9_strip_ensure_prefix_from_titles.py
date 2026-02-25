"""Strip 'Ensure'/'Configure'/'Verify' prefix from rule titles.

Revision ID: c4d5e6f7a8b9
Revises: b7e4f1a2c3d5
Create Date: 2025-02-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c4d5e6f7a8b9"
down_revision = "b7e4f1a2c3d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Strip leading 'Ensure ', 'Configure ', 'Verify ' from all rule titles."""
    conn = op.get_bind()
    for prefix in ("Ensure ", "Configure ", "Verify "):
        conn.execute(
            sa.text(
                "UPDATE rules SET title = SUBSTR(title, :offset) "
                "WHERE title LIKE :pattern"
            ),
            {"offset": len(prefix) + 1, "pattern": f"{prefix}%"},
        )


def downgrade() -> None:
    """No automated downgrade — titles cannot be reliably re-prefixed."""
    pass
