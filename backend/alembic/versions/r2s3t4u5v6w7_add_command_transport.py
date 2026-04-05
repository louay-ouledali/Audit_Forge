"""Add command_transport column to rule_commands table.

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-03-26

Supports per-rule transport tagging (sql, shell, powershell, cli, api)
for dual-connector routing in the scan executor.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "r2s3t4u5v6w7"
down_revision = "q1r2s3t4u5v6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    columns = {c["name"] for c in sa.inspect(conn).get_columns("rule_commands")}
    if "command_transport" not in columns:
        with op.batch_alter_table("rule_commands") as batch_op:
            batch_op.add_column(
                sa.Column("command_transport", sa.String(), nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("rule_commands") as batch_op:
        batch_op.drop_column("command_transport")
