"""Add original_command column to rule_commands.

Revision ID: d3e4f5g6h7i8
Revises: c2d3e4f5g6h7
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa

revision = "d3e4f5g6h7i8"
down_revision = "c2d3e4f5g6h7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("rule_commands")}
    if "original_command" not in cols:
        with op.batch_alter_table("rule_commands") as batch:
            batch.add_column(sa.Column("original_command", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("rule_commands") as batch:
        batch.drop_column("original_command")
