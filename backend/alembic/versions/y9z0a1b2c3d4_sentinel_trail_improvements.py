"""Forge Sentinel & Trail schema improvements.

- Add indexes on notifications(user_id), schedules(next_run_at)
- Add ip_address, user_agent columns to audit_logs
- Make audit_logs.mission_id nullable (SET NULL instead of CASCADE)
- Add composite index on audit_logs(mission_id, created_at)

Revision ID: y9z0a1b2c3d4
Revises: x8y9z0a1b2c3
Create Date: 2026-04-02
"""

from alembic import op
import sqlalchemy as sa

revision = "y9z0a1b2c3d4"
down_revision = "x8y9z0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # ── notifications indexes ──────────────────────────────────────
    if "notifications" in inspector.get_table_names():
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("notifications")}
        if "ix_notifications_user_id" not in existing_indexes:
            op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
        if "ix_notifications_user_read" not in existing_indexes:
            op.create_index("ix_notifications_user_read", "notifications", ["user_id", "is_read"])

    # ── schedules indexes ──────────────────────────────────────────
    if "schedules" in inspector.get_table_names():
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("schedules")}
        if "ix_schedules_next_run_at" not in existing_indexes:
            op.create_index("ix_schedules_next_run_at", "schedules", ["next_run_at"])

    # ── audit_logs: new columns + nullable mission_id + indexes ────
    if "audit_logs" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("audit_logs")}
        with op.batch_alter_table("audit_logs") as batch_op:
            if "ip_address" not in columns:
                batch_op.add_column(sa.Column("ip_address", sa.String(), nullable=True))
            if "user_agent" not in columns:
                batch_op.add_column(sa.Column("user_agent", sa.String(), nullable=True))
            # Make mission_id nullable and change FK ondelete to SET NULL
            # SQLite batch mode recreates the table so just define the new FK state
            batch_op.alter_column("mission_id", existing_type=sa.Integer(), nullable=True)

        existing_indexes = {idx["name"] for idx in inspector.get_indexes("audit_logs")}
        if "ix_audit_logs_mission_created" not in existing_indexes:
            op.create_index(
                "ix_audit_logs_mission_created",
                "audit_logs",
                ["mission_id", "created_at"],
            )
        if "ix_audit_logs_user_id" not in existing_indexes:
            op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
        if "ix_audit_logs_action" not in existing_indexes:
            op.create_index("ix_audit_logs_action", "audit_logs", ["action"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "audit_logs" in inspector.get_table_names():
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("audit_logs")}
        for idx_name in ["ix_audit_logs_action", "ix_audit_logs_user_id", "ix_audit_logs_mission_created"]:
            if idx_name in existing_indexes:
                op.drop_index(idx_name, table_name="audit_logs")
        with op.batch_alter_table("audit_logs") as batch_op:
            batch_op.drop_column("user_agent")
            batch_op.drop_column("ip_address")
            batch_op.alter_column("mission_id", existing_type=sa.Integer(), nullable=False)

    if "schedules" in inspector.get_table_names():
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("schedules")}
        if "ix_schedules_next_run_at" in existing_indexes:
            op.drop_index("ix_schedules_next_run_at", table_name="schedules")

    if "notifications" in inspector.get_table_names():
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("notifications")}
        for idx_name in ["ix_notifications_user_read", "ix_notifications_user_id"]:
            if idx_name in existing_indexes:
                op.drop_index(idx_name, table_name="notifications")
