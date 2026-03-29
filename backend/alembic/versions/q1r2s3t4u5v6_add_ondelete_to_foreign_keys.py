"""Add ondelete policies to unprotected foreign keys.

Revision ID: q1r2s3t4u5v6
Revises: p1h2a3s4e5_1
Create Date: 2026-03-25 12:00:00.000000

Fixes bug #19: deleting a benchmark/rule/preset/mission left orphaned rows
in scans, findings, scan_presets, and mission_analyses with dangling FKs.

Changes:
  - findings.rule_id:                   ADD ondelete=SET NULL, nullable=True
  - scans.benchmark_id:                 ADD ondelete=SET NULL, nullable=True
  - scans.preset_id:                    ADD ondelete=SET NULL
  - scan_presets.benchmark_id:          ADD ondelete=CASCADE
  - mission_analyses.compared_mission_id: ADD ondelete=SET NULL
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "q1r2s3t4u5v6"
down_revision = "p1h2a3s4e5_1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite requires batch mode to alter FK constraints.
    # Each batch_alter_table recreates the table behind the scenes.

    # ── findings.rule_id: SET NULL on rule deletion ──
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.alter_column("rule_id", existing_type=sa.Integer(), nullable=True)
        batch_op.drop_constraint("fk_findings_rule_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_findings_rule_id", "rules", ["rule_id"], ["id"], ondelete="SET NULL"
        )

    # ── scans.benchmark_id: SET NULL on benchmark deletion ──
    # ── scans.preset_id:    SET NULL on preset deletion ──
    with op.batch_alter_table("scans", schema=None) as batch_op:
        batch_op.alter_column("benchmark_id", existing_type=sa.Integer(), nullable=True)

        batch_op.drop_constraint("fk_scans_benchmark_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_scans_benchmark_id", "benchmarks", ["benchmark_id"], ["id"], ondelete="SET NULL"
        )

        batch_op.drop_constraint("fk_scans_preset_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_scans_preset_id", "scan_presets", ["preset_id"], ["id"], ondelete="SET NULL"
        )

    # ── scan_presets.benchmark_id: CASCADE on benchmark deletion ──
    with op.batch_alter_table("scan_presets", schema=None) as batch_op:
        batch_op.drop_constraint("fk_scan_presets_benchmark_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_scan_presets_benchmark_id", "benchmarks", ["benchmark_id"], ["id"], ondelete="CASCADE"
        )

    # ── mission_analyses.compared_mission_id: SET NULL on mission deletion ──
    with op.batch_alter_table("mission_analyses", schema=None) as batch_op:
        batch_op.drop_constraint("fk_mission_analyses_compared_mission_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_mission_analyses_compared_mission_id",
            "missions",
            ["compared_mission_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    # Reverse: remove ondelete policies and restore NOT NULL where applicable.

    with op.batch_alter_table("mission_analyses", schema=None) as batch_op:
        batch_op.drop_constraint("fk_mission_analyses_compared_mission_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_mission_analyses_compared_mission_id",
            "missions",
            ["compared_mission_id"],
            ["id"],
        )

    with op.batch_alter_table("scan_presets", schema=None) as batch_op:
        batch_op.drop_constraint("fk_scan_presets_benchmark_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_scan_presets_benchmark_id", "benchmarks", ["benchmark_id"], ["id"]
        )

    with op.batch_alter_table("scans", schema=None) as batch_op:
        batch_op.drop_constraint("fk_scans_preset_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_scans_preset_id", "scan_presets", ["preset_id"], ["id"]
        )
        batch_op.drop_constraint("fk_scans_benchmark_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_scans_benchmark_id", "benchmarks", ["benchmark_id"], ["id"]
        )
        batch_op.alter_column("benchmark_id", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.drop_constraint("fk_findings_rule_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_findings_rule_id", "rules", ["rule_id"], ["id"]
        )
        batch_op.alter_column("rule_id", existing_type=sa.Integer(), nullable=False)
