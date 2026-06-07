"""Add config audit tables (config_snapshots, mission_topology) and columns.

Revision ID: b1c2d3e4f5g6
Revises: z0a1b2c3d4e5
Create Date: 2026-04-11
"""
from alembic import op
import sqlalchemy as sa

revision = "b1c2d3e4f5g6"
down_revision = "z0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = sa.inspect(conn).get_table_names()

    # config_snapshots table
    if "config_snapshots" not in tables:
        op.create_table(
            "config_snapshots",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("target_id", sa.Integer, sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("scan_id", sa.Integer, sa.ForeignKey("scans.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source", sa.String, nullable=False, server_default="upload"),
            sa.Column("config_format", sa.String, nullable=True),
            sa.Column("raw_config", sa.Text, nullable=False),
            sa.Column("config_hash", sa.String, nullable=False),
            sa.Column("device_hostname", sa.String, nullable=True),
            sa.Column("platform_detected", sa.String, nullable=True),
            sa.Column("line_count", sa.Integer, nullable=True),
            sa.Column("snapshot_at", sa.DateTime, nullable=False),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_config_snapshots_target_id", "config_snapshots", ["target_id"])

    # mission_topology table
    if "mission_topology" not in tables:
        op.create_table(
            "mission_topology",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("mission_id", sa.Integer, sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("graph_json", sa.Text, nullable=False),
            sa.Column("auto_layout_json", sa.Text, nullable=True),
            sa.Column("user_layout_json", sa.Text, nullable=True),
            sa.Column("last_rebuilt_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )

    # Column additions (with idempotency guards)
    def _has_column(table: str, column: str) -> bool:
        return column in {c["name"] for c in sa.inspect(conn).get_columns(table)}

    # targets.config_pull_method
    if not _has_column("targets", "config_pull_method"):
        with op.batch_alter_table("targets") as batch_op:
            batch_op.add_column(sa.Column("config_pull_method", sa.String, nullable=True))

    # targets.latest_config_id
    if not _has_column("targets", "latest_config_id"):
        with op.batch_alter_table("targets") as batch_op:
            batch_op.add_column(sa.Column("latest_config_id", sa.Integer, nullable=True))
            batch_op.create_foreign_key(
                "fk_targets_latest_config_id",
                "config_snapshots", ["latest_config_id"], ["id"],
                ondelete="SET NULL",
            )

    # scans.config_snapshot_id
    if not _has_column("scans", "config_snapshot_id"):
        with op.batch_alter_table("scans") as batch_op:
            batch_op.add_column(sa.Column("config_snapshot_id", sa.Integer, nullable=True))
            batch_op.create_foreign_key(
                "fk_scans_config_snapshot_id",
                "config_snapshots", ["config_snapshot_id"], ["id"],
                ondelete="SET NULL",
            )

    # findings.evaluation_source
    if not _has_column("findings", "evaluation_source"):
        with op.batch_alter_table("findings") as batch_op:
            batch_op.add_column(sa.Column("evaluation_source", sa.String, nullable=True))


def downgrade() -> None:
    conn = op.get_bind()

    def _has_column(table: str, column: str) -> bool:
        return column in {c["name"] for c in sa.inspect(conn).get_columns(table)}

    if _has_column("findings", "evaluation_source"):
        with op.batch_alter_table("findings") as batch_op:
            batch_op.drop_column("evaluation_source")

    if _has_column("scans", "config_snapshot_id"):
        with op.batch_alter_table("scans") as batch_op:
            batch_op.drop_column("config_snapshot_id")

    if _has_column("targets", "latest_config_id"):
        with op.batch_alter_table("targets") as batch_op:
            batch_op.drop_column("latest_config_id")

    if _has_column("targets", "config_pull_method"):
        with op.batch_alter_table("targets") as batch_op:
            batch_op.drop_column("config_pull_method")

    tables = sa.inspect(conn).get_table_names()
    if "mission_topology" in tables:
        op.drop_table("mission_topology")
    if "config_snapshots" in tables:
        op.drop_table("config_snapshots")
