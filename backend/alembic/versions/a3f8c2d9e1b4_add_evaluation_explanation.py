"""Add evaluation_explanation to findings

Revision ID: a3f8c2d9e1b4
Revises: 823921b21a0f
Create Date: 2026-02-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f8c2d9e1b4'
down_revision = '823921b21a0f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('findings', sa.Column('evaluation_explanation', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('findings', 'evaluation_explanation')
