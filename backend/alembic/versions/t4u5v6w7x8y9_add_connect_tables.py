"""Add connect_sessions and connect_agents tables.

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-03-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "t4u5v6w7x8y9"
down_revision = "s3t4u5v6w7x8"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    if not _table_exists("connect_sessions"):
        op.create_table(
            "connect_sessions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("enrollment_code", sa.String(8), unique=True, nullable=False, index=True),
            sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
            sa.Column("mission_id", sa.Integer, sa.ForeignKey("missions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String, server_default="active"),
            sa.Column("created_by", sa.String, nullable=True),
            sa.Column("created_at", sa.DateTime),
            sa.Column("expires_at", sa.DateTime, nullable=False),
            sa.Column("max_agent_lifetime_seconds", sa.Integer, server_default="14400"),
            sa.Column("notes", sa.Text, nullable=True),
        )
    else:
        # Table exists from prior run — add mission_id if missing
        bind = op.get_bind()
        insp = sa.inspect(bind)
        cols = [c["name"] for c in insp.get_columns("connect_sessions")]
        if "mission_id" not in cols:
            with op.batch_alter_table("connect_sessions") as batch_op:
                batch_op.add_column(sa.Column("mission_id", sa.Integer, nullable=True))
                batch_op.create_foreign_key(
                    "fk_connect_sessions_mission_id", "missions",
                    ["mission_id"], ["id"], ondelete="SET NULL",
                )

    if not _table_exists("connect_agents"):
        op.create_table(
            "connect_agents",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.Integer, sa.ForeignKey("connect_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token", sa.String, unique=True, nullable=False, index=True),
            sa.Column("hostname", sa.String, nullable=True),
            sa.Column("ip_address", sa.String, nullable=True),
            sa.Column("os_type", sa.String, nullable=True),
            sa.Column("os_version", sa.String, nullable=True),
            sa.Column("status", sa.String, server_default="pending"),
            sa.Column("connected_at", sa.DateTime, nullable=True),
            sa.Column("disconnected_at", sa.DateTime, nullable=True),
            sa.Column("target_id", sa.Integer, sa.ForeignKey("targets.id", ondelete="SET NULL"), nullable=True),
            sa.Column("system_info", sa.Text, nullable=True),
        )


def downgrade() -> None:
    if _table_exists("connect_agents"):
        op.drop_table("connect_agents")
    if _table_exists("connect_sessions"):
        op.drop_table("connect_sessions")
