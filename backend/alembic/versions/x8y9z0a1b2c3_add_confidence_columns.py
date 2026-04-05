"""Add confidence_score and confidence_source columns to rule_commands.

Revision ID: x8y9z0a1b2c3
Revises: v6w7x8y9z0a1
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa

revision = "x8y9z0a1b2c3"
down_revision = "v6w7x8y9z0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    columns = {c["name"] for c in sa.inspect(conn).get_columns("rule_commands")}
    with op.batch_alter_table("rule_commands") as batch_op:
        if "confidence_score" not in columns:
            batch_op.add_column(sa.Column("confidence_score", sa.Float(), nullable=True, server_default="0.5"))
        if "confidence_source" not in columns:
            batch_op.add_column(sa.Column("confidence_source", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("rule_commands") as batch_op:
        batch_op.drop_column("confidence_source")
        batch_op.drop_column("confidence_score")
