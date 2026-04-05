"""Add command_corrections table for self-healing tracking.

Revision ID: w7x8y9z0a1b2
Revises: x8y9z0a1b2c3
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa

revision = "w7x8y9z0a1b2"
down_revision = "x8y9z0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = sa.inspect(conn).get_table_names()
    if "command_corrections" in tables:
        return
    op.create_table(
        "command_corrections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_command_id", sa.Integer(),
                  sa.ForeignKey("rule_commands.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_command", sa.Text(), nullable=False),
        sa.Column("original_expression", sa.Text(), nullable=True),
        sa.Column("error_output", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("corrected_command", sa.Text(), nullable=True),
        sa.Column("corrected_expression", sa.Text(), nullable=True),
        sa.Column("correction_source", sa.String(), nullable=False),
        sa.Column("correction_notes", sa.Text(), nullable=True),
        sa.Column("correction_worked", sa.Integer(), nullable=True),
        sa.Column("new_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("command_corrections")
