"""Add benchmark_groups, command_cache tables + version/framework columns.

Revision ID: p1h2a3s4e5_1
Revises: m1e2r3g4e5h6
Create Date: 2026-03-10 10:00:00.000000

Phase 1 of the Benchmark Studio Infinite Scalability upgrade:
  - benchmark_groups table (version grouping)
  - command_cache table (cross-benchmark command reuse)
  - benchmarks.group_id, benchmarks.framework, benchmarks.is_baseline
  - rules.framework_ref
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

# revision identifiers, used by Alembic.
revision = "p1h2a3s4e5_1"
down_revision = "d9efd8724116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing_tables = inspector.get_table_names()

    # ── benchmark_groups ──
    if "benchmark_groups" in existing_tables:
        # Drop auto-created (empty) table so we can recreate with proper constraints
        op.drop_table("benchmark_groups")
    op.create_table(
        "benchmark_groups",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("canonical_name", sa.String, nullable=False),
        sa.Column("platform", sa.String, nullable=False),
        sa.Column("platform_family", sa.String, nullable=False),
        sa.Column("framework", sa.String, nullable=False, server_default="cis"),
        sa.Column("created_at", sa.DateTime),
        sa.UniqueConstraint("canonical_name", "platform", name="uq_bgr_canonical_platform"),
    )

    # ── command_cache ──
    if "command_cache" in existing_tables:
        op.drop_table("command_cache")
    op.create_table(
        "command_cache",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("platform", sa.String, nullable=False),
        sa.Column("platform_family", sa.String, nullable=False),
        sa.Column("section_number", sa.String, nullable=False),
        sa.Column("rule_title_normalized", sa.String, nullable=False),
        sa.Column("audit_command", sa.Text),
        sa.Column("expected_output_regex", sa.Text),
        sa.Column("expected_output_description", sa.Text),
        sa.Column("remediation_command", sa.Text),
        sa.Column("remediation_description", sa.Text),
        sa.Column("source_benchmark_id", sa.Integer, sa.ForeignKey("benchmarks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_framework", sa.String, server_default="cis"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("match_type", sa.String, nullable=False, server_default="exact_version"),
        sa.Column("verification_status", sa.String, server_default="unverified"),
        sa.Column("hit_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("cache_key", "platform", name="uq_command_cache_key_platform"),
    )
    op.create_index("ix_command_cache_platform_section", "command_cache", ["platform", "section_number"])

    # ── benchmarks: new columns ──
    bench_cols = {c["name"] for c in inspector.get_columns("benchmarks")}
    with op.batch_alter_table("benchmarks") as batch_op:
        if "group_id" not in bench_cols:
            batch_op.add_column(sa.Column("group_id", sa.Integer, nullable=True))
            batch_op.create_foreign_key("fk_benchmarks_group_id", "benchmark_groups", ["group_id"], ["id"], ondelete="SET NULL")
        if "framework" not in bench_cols:
            batch_op.add_column(sa.Column("framework", sa.String, server_default="cis"))
        if "is_baseline" not in bench_cols:
            batch_op.add_column(sa.Column("is_baseline", sa.Boolean, server_default="0"))

    # ── rules: new column ──
    rule_cols = {c["name"] for c in inspector.get_columns("rules")}
    with op.batch_alter_table("rules") as batch_op:
        if "framework_ref" not in rule_cols:
            batch_op.add_column(sa.Column("framework_ref", sa.String, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("rules") as batch_op:
        batch_op.drop_column("framework_ref")

    with op.batch_alter_table("benchmarks") as batch_op:
        batch_op.drop_column("is_baseline")
        batch_op.drop_column("framework")
        batch_op.drop_column("group_id")

    op.drop_index("ix_command_cache_platform_section", table_name="command_cache")
    op.drop_table("command_cache")
    op.drop_table("benchmark_groups")
