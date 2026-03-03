"""add discovery_cache table

Revision ID: g1h2i3j4k5l6
Revises: f1a2b3c4d5e6
Create Date: 2025-07-26 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "g1h2i3j4k5l6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ip_address", sa.String(45), nullable=False, index=True),
        sa.Column("mac_address", sa.String(17), nullable=True, index=True),
        sa.Column("subnet", sa.String(50), nullable=True, index=True),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column("os_guess", sa.String(50), nullable=True),
        sa.Column("os_version", sa.String(255), nullable=True),
        sa.Column("vendor", sa.String(255), nullable=True),
        sa.Column("device_model", sa.String(255), nullable=True),
        sa.Column("firmware", sa.String(255), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("detection_method", sa.String(255), nullable=True),
        sa.Column("confidence", sa.Integer(), default=0),
        sa.Column("open_ports_json", sa.Text(), nullable=True),
        sa.Column("connection_methods_json", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index(
        "ix_discovery_cache_mac_subnet",
        "discovery_cache",
        ["mac_address", "subnet"],
    )


def downgrade() -> None:
    op.drop_index("ix_discovery_cache_mac_subnet", table_name="discovery_cache")
    op.drop_table("discovery_cache")
