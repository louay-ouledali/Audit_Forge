"""Add verify_tls column to targets and token_blacklist table.

Revision ID: c2d3e4f5g6h7
Revises: b2c3d4e5f6g7, b1c2d3e4f5g6
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5g6h7"
down_revision = ("b2c3d4e5f6g7", "b1c2d3e4f5g6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # verify_tls on targets (default True) — idempotent
    target_cols = {c["name"] for c in inspector.get_columns("targets")}
    if "verify_tls" not in target_cols:
        with op.batch_alter_table("targets") as batch:
            batch.add_column(sa.Column("verify_tls", sa.Boolean(), nullable=False, server_default="1"))

    # token_blacklist for JWT revocation (Phase 4 auth) — idempotent
    if "token_blacklist" not in inspector.get_table_names():
        op.create_table(
            "token_blacklist",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("jti", sa.String(), nullable=False, unique=True, index=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("token_blacklist")
    with op.batch_alter_table("targets") as batch:
        batch.drop_column("verify_tls")
