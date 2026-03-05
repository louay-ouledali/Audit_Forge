"""add_ad_credentials_to_clients

Revision ID: d9efd8724116
Revises: m1e2r3g4e5h6
Create Date: 2026-03-05 13:50:18.141073

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9efd8724116'
down_revision: Union[str, Sequence[str], None] = 'm1e2r3g4e5h6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('clients', sa.Column('ad_domain', sa.String(), nullable=True))
    op.add_column('clients', sa.Column('ad_dc_host', sa.String(), nullable=True))
    op.add_column('clients', sa.Column('ad_username', sa.String(), nullable=True))
    op.add_column('clients', sa.Column('ad_password_encrypted', sa.Text(), nullable=True))
    op.add_column('clients', sa.Column('ad_use_ssl', sa.Integer(), nullable=True))
    op.add_column('clients', sa.Column('ad_base_ou', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('clients', 'ad_base_ou')
    op.drop_column('clients', 'ad_use_ssl')
    op.drop_column('clients', 'ad_password_encrypted')
    op.drop_column('clients', 'ad_username')
    op.drop_column('clients', 'ad_dc_host')
    op.drop_column('clients', 'ad_domain')
