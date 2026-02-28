"""add target scanning enhancement fields and scan_batches tables

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-02-28

Phase 1 of the Targets & Scanning Tab Redesign:
- Adds nullable columns to targets table (platform_subtype, default_benchmark_id,
  connection health tracking, DB-specific, network device-specific fields).
- Creates scan_batches and scan_batch_items tables for "Scan All" batch operations.

All new columns are nullable so existing data is unaffected.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column already exists (SQLite-safe)."""
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result)


def _table_exists(table: str) -> bool:
    """Check if a table already exists."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # ── New columns on targets table ──────────────────────────
    new_cols = [
        ("platform_subtype", sa.String()),
        ("default_benchmark_id", sa.Integer()),
        ("last_connection_test", sa.DateTime()),
        ("connection_status", sa.String()),
        ("connection_error", sa.Text()),
        ("db_name", sa.String()),
        ("db_instance", sa.String()),
        ("enable_password_encrypted", sa.Text()),
        ("device_type", sa.String()),
    ]
    for col_name, col_type in new_cols:
        if not _column_exists("targets", col_name):
            op.add_column("targets", sa.Column(col_name, col_type, nullable=True))

    # ── scan_batches table ────────────────────────────────────
    if not _table_exists("scan_batches"):
        op.create_table(
            "scan_batches",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "mission_id",
                sa.Integer(),
                sa.ForeignKey("missions.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("status", sa.String(), server_default="pending"),
            sa.Column("total_targets", sa.Integer(), server_default="0"),
            sa.Column("completed_targets", sa.Integer(), server_default="0"),
            sa.Column("failed_targets", sa.Integer(), server_default="0"),
            sa.Column("skipped_targets", sa.Integer(), server_default="0"),
            sa.Column("concurrency", sa.Integer(), server_default="3"),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )

    # ── scan_batch_items table ────────────────────────────────
    if not _table_exists("scan_batch_items"):
        op.create_table(
            "scan_batch_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "batch_id",
                sa.Integer(),
                sa.ForeignKey("scan_batches.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "target_id",
                sa.Integer(),
                sa.ForeignKey("targets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "benchmark_id",
                sa.Integer(),
                sa.ForeignKey("benchmarks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "scan_id",
                sa.Integer(),
                sa.ForeignKey("scans.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("status", sa.String(), server_default="pending"),
            sa.Column("skip_reason", sa.String(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime()),
        )


def downgrade() -> None:
    op.drop_table("scan_batch_items")
    op.drop_table("scan_batches")

    with op.batch_alter_table("targets", schema=None) as batch_op:
        batch_op.drop_column("device_type")
        batch_op.drop_column("enable_password_encrypted")
        batch_op.drop_column("db_instance")
        batch_op.drop_column("db_name")
        batch_op.drop_column("connection_error")
        batch_op.drop_column("connection_status")
        batch_op.drop_column("last_connection_test")
        batch_op.drop_column("default_benchmark_id")
        batch_op.drop_column("platform_subtype")
