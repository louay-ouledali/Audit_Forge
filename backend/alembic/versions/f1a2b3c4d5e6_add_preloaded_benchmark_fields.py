"""add preloaded benchmark intelligence fields

Revision ID: f1a2b3c4d5e6
Revises: e6f7a8b9c0d1
Create Date: 2026-02-27

Adds nullable columns to benchmarks, rules, and rule_commands tables
to support pre-loaded benchmark packs with baked-in intelligence
(FP conditions, evidence interpretations, narrative groups, MITRE
mappings, risk weights, remediation metadata).

All columns are nullable so existing data is unaffected.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Benchmark table ──────────────────────────────────────
    with op.batch_alter_table("benchmarks") as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.String(), server_default="user_imported", nullable=True)
        )
        batch_op.add_column(
            sa.Column("preloaded_version", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("pack_hash", sa.String(), nullable=True)
        )

    # ── Rule table ───────────────────────────────────────────
    with op.batch_alter_table("rules") as batch_op:
        batch_op.add_column(
            sa.Column("narrative_group", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("security_themes_json", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("attack_chain_tags_json", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("mitre_attack_json", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("risk_weight", sa.Integer(), nullable=True, server_default="5")
        )
        batch_op.add_column(
            sa.Column("related_rules_json", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("group_with_json", sa.Text(), nullable=True)
        )

    # ── RuleCommand table ────────────────────────────────────
    with op.batch_alter_table("rule_commands") as batch_op:
        batch_op.add_column(
            sa.Column("empty_output_interpretation", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("output_value_map_json", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("fp_conditions_json", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("remediation_gpo_path", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("remediation_risk", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("safe_to_automate", sa.Boolean(), nullable=True, server_default="0")
        )
        batch_op.add_column(
            sa.Column("requires_restart", sa.Boolean(), nullable=True, server_default="0")
        )


def downgrade() -> None:
    # ── RuleCommand table ────────────────────────────────────
    with op.batch_alter_table("rule_commands") as batch_op:
        batch_op.drop_column("requires_restart")
        batch_op.drop_column("safe_to_automate")
        batch_op.drop_column("remediation_risk")
        batch_op.drop_column("remediation_gpo_path")
        batch_op.drop_column("fp_conditions_json")
        batch_op.drop_column("output_value_map_json")
        batch_op.drop_column("empty_output_interpretation")

    # ── Rule table ───────────────────────────────────────────
    with op.batch_alter_table("rules") as batch_op:
        batch_op.drop_column("group_with_json")
        batch_op.drop_column("related_rules_json")
        batch_op.drop_column("risk_weight")
        batch_op.drop_column("mitre_attack_json")
        batch_op.drop_column("attack_chain_tags_json")
        batch_op.drop_column("security_themes_json")
        batch_op.drop_column("narrative_group")

    # ── Benchmark table ──────────────────────────────────────
    with op.batch_alter_table("benchmarks") as batch_op:
        batch_op.drop_column("pack_hash")
        batch_op.drop_column("preloaded_version")
        batch_op.drop_column("source")
