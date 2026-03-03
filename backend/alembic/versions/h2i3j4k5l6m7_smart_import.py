"""Smart Import — add import_records table + new columns on findings/benchmarks/rules.

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-03-03 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "h2i3j4k5l6m7"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": name},
    )
    return result.scalar() is not None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result)


def upgrade() -> None:
    # ── New table: import_records ─────────────────────────────
    if not _table_exists("import_records"):
        op.create_table(
            "import_records",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("scan_id", sa.Integer, sa.ForeignKey("scans.id", ondelete="SET NULL"), nullable=True),
            sa.Column("benchmark_id", sa.Integer, sa.ForeignKey("benchmarks.id", ondelete="SET NULL"), nullable=True),
            sa.Column("target_id", sa.Integer, sa.ForeignKey("targets.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_filename", sa.String, nullable=True),
            sa.Column("source_format", sa.String, nullable=True),
            sa.Column("source_tool", sa.String, nullable=True),
            sa.Column("platform_detected", sa.String, nullable=True),
            sa.Column("benchmark_detected", sa.String, nullable=True),
            sa.Column("version_detected", sa.String, nullable=True),
            sa.Column("findings_imported", sa.Integer, default=0),
            sa.Column("metadata_json", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=True),
        )

    # ── findings: +2 columns ─────────────────────────────────
    with op.batch_alter_table("findings") as batch_op:
        if not _column_exists("findings", "import_source"):
            batch_op.add_column(sa.Column("import_source", sa.String, nullable=True))
        if not _column_exists("findings", "import_metadata"):
            batch_op.add_column(sa.Column("import_metadata", sa.Text, nullable=True))

    # ── benchmarks: +4 columns ───────────────────────────────
    with op.batch_alter_table("benchmarks", naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s"}) as batch_op:
        if not _column_exists("benchmarks", "is_editable"):
            batch_op.add_column(sa.Column("is_editable", sa.Boolean, nullable=True, server_default="0"))
        if not _column_exists("benchmarks", "parent_benchmark_id"):
            batch_op.add_column(sa.Column(
                "parent_benchmark_id",
                sa.Integer,
                nullable=True,
            ))
        if not _column_exists("benchmarks", "migration_readiness"):
            batch_op.add_column(sa.Column("migration_readiness", sa.Float, nullable=True))
        if not _column_exists("benchmarks", "source_details"):
            batch_op.add_column(sa.Column("source_details", sa.Text, nullable=True))

    # ── rules: +2 columns ───────────────────────────────────
    with op.batch_alter_table("rules") as batch_op:
        if not _column_exists("rules", "source"):
            batch_op.add_column(sa.Column("source", sa.String, nullable=True))
        if not _column_exists("rules", "framework_mappings"):
            batch_op.add_column(sa.Column("framework_mappings", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("rules") as batch_op:
        batch_op.drop_column("framework_mappings")
        batch_op.drop_column("source")

    with op.batch_alter_table("benchmarks") as batch_op:
        batch_op.drop_column("source_details")
        batch_op.drop_column("migration_readiness")
        batch_op.drop_column("parent_benchmark_id")
        batch_op.drop_column("is_editable")

    with op.batch_alter_table("findings") as batch_op:
        batch_op.drop_column("import_metadata")
        batch_op.drop_column("import_source")

    op.drop_table("import_records")
