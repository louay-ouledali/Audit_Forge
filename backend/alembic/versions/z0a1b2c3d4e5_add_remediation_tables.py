"""Add remediation_sessions and remediation_items tables for Forge Resolve.

Revision ID: z0a1b2c3d4e5
Revises: y9z0a1b2c3d4
Create Date: 2026-04-07
"""

from alembic import op
import sqlalchemy as sa

revision = "z0a1b2c3d4e5"
down_revision = "y9z0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "remediation_sessions" not in existing_tables:
        op.create_table(
            "remediation_sessions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("mission_id", sa.Integer, sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_id", sa.Integer, sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by", sa.String, nullable=False, server_default="system"),
            sa.Column("status", sa.String, nullable=False, server_default="draft"),
            sa.Column("execution_mode", sa.String, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("executed_at", sa.DateTime, nullable=True),
            sa.Column("completed_at", sa.DateTime, nullable=True),
            sa.Column("total_items", sa.Integer, server_default="0"),
            sa.Column("succeeded_items", sa.Integer, server_default="0"),
            sa.Column("failed_items", sa.Integer, server_default="0"),
            sa.Column("skipped_items", sa.Integer, server_default="0"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("scan_ids_json", sa.Text, nullable=True),
        )
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("remediation_sessions")} if "remediation_sessions" in inspector.get_table_names() else set()
        if "ix_remediation_sessions_mission_id" not in existing_indexes:
            op.create_index("ix_remediation_sessions_mission_id", "remediation_sessions", ["mission_id"])
        if "ix_remediation_sessions_target_id" not in existing_indexes:
            op.create_index("ix_remediation_sessions_target_id", "remediation_sessions", ["target_id"])

    if "remediation_items" not in existing_tables:
        op.create_table(
            "remediation_items",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.Integer, sa.ForeignKey("remediation_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("finding_id", sa.Integer, sa.ForeignKey("findings.id", ondelete="SET NULL"), nullable=True),
            sa.Column("rule_id", sa.Integer, sa.ForeignKey("rules.id", ondelete="SET NULL"), nullable=True),
            sa.Column("section_number", sa.String, nullable=False),
            sa.Column("rule_title", sa.String, nullable=False),
            sa.Column("severity", sa.String, nullable=True),
            sa.Column("remediation_command", sa.Text, nullable=True),
            sa.Column("command_source", sa.String, nullable=False, server_default="benchmark"),
            sa.Column("command_transport", sa.String, nullable=True),
            sa.Column("selected", sa.Boolean, server_default="1"),
            sa.Column("status", sa.String, nullable=False, server_default="pending"),
            sa.Column("execution_output", sa.Text, nullable=True),
            sa.Column("execution_error", sa.Text, nullable=True),
            sa.Column("executed_at", sa.DateTime, nullable=True),
            sa.Column("order_index", sa.Integer, server_default="0"),
            sa.Column("requires_privilege", sa.Boolean, server_default="0"),
        )
        existing_indexes2 = {idx["name"] for idx in inspector.get_indexes("remediation_items")} if "remediation_items" in inspector.get_table_names() else set()
        if "ix_remediation_items_session_id" not in existing_indexes2:
            op.create_index("ix_remediation_items_session_id", "remediation_items", ["session_id"])


def downgrade() -> None:
    op.drop_table("remediation_items")
    op.drop_table("remediation_sessions")
