"""Add Phase 3 validation columns

Revision ID: b7e4f1a2c3d5
Revises: a3f8c2d9e1b4
Create Date: 2026-02-16 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e4f1a2c3d5'
down_revision = 'a3f8c2d9e1b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Benchmark: Phase 3 status tracking
    bench_cols = {c["name"] for c in inspector.get_columns("benchmarks")}
    if "phase3_status" not in bench_cols:
        op.add_column('benchmarks', sa.Column('phase3_status', sa.String(), nullable=True))
    if "phase3_stats" not in bench_cols:
        op.add_column('benchmarks', sa.Column('phase3_stats', sa.Text(), nullable=True))

    # RuleCommand: Per-rule validation results
    rc_cols = {c["name"] for c in inspector.get_columns("rule_commands")}
    if "validation_status" not in rc_cols:
        op.add_column('rule_commands', sa.Column('validation_status', sa.String(), nullable=True))
    if "validation_confidence" not in rc_cols:
        op.add_column('rule_commands', sa.Column('validation_confidence', sa.String(), nullable=True))
    if "validation_corrections" not in rc_cols:
        op.add_column('rule_commands', sa.Column('validation_corrections', sa.Text(), nullable=True))
    if "validation_notes" not in rc_cols:
        op.add_column('rule_commands', sa.Column('validation_notes', sa.Text(), nullable=True))
    if "validated_at" not in rc_cols:
        op.add_column('rule_commands', sa.Column('validated_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('rule_commands', 'validated_at')
    op.drop_column('rule_commands', 'validation_notes')
    op.drop_column('rule_commands', 'validation_corrections')
    op.drop_column('rule_commands', 'validation_confidence')
    op.drop_column('rule_commands', 'validation_status')
    op.drop_column('benchmarks', 'phase3_stats')
    op.drop_column('benchmarks', 'phase3_status')
