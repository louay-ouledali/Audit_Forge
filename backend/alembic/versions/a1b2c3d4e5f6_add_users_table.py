"""Add users table for Forge Gatekeeper auth.

Revision ID: a1b2c3d4e5f6
Revises: w7x8y9z0a1b2
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
from passlib.hash import bcrypt

revision = "a1b2c3d4e5f6"
down_revision = "w7x8y9z0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = sa.inspect(conn).get_table_names()
    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("username", sa.String(), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(), nullable=False),
            sa.Column("full_name", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("last_login", sa.DateTime(), nullable=True),
        )
    # Seed default admin if table is empty
    result = conn.execute(sa.text("SELECT COUNT(*) FROM users"))
    if result.scalar() == 0:
        op.execute(
            sa.text(
                "INSERT INTO users (username, password_hash, full_name, created_at) "
                "VALUES (:u, :p, :n, :t)"
            ).bindparams(
                u="admin",
                p=bcrypt.hash("auditforge"),
                n="Administrator",
                t="2026-03-31T00:00:00",
            )
        )


def downgrade() -> None:
    op.drop_table("users")
