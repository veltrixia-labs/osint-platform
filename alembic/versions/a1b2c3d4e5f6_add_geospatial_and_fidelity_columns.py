"""add geospatial and fidelity columns

Revision ID: a1b2c3d4e5f6
Revises: 5e9f8c7d6a2b
Create Date: 2026-04-01 15:10:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '5e9f8c7d6a2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update AlertLog table
    op.add_column('alert_logs', sa.Column('fidelity_score', sa.Float(), nullable=True, server_default='0.0'))
    op.add_column('alert_logs', sa.Column('is_high_fidelity', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('alert_logs', sa.Column('location_lat', sa.Float(), nullable=True))
    op.add_column('alert_logs', sa.Column('location_lng', sa.Float(), nullable=True))

    # 2. Update Report table
    op.add_column('reports', sa.Column('location_lat', sa.Float(), nullable=True))
    op.add_column('reports', sa.Column('location_lng', sa.Float(), nullable=True))


def downgrade() -> None:
    # 1. Revert Report table
    op.drop_column('reports', 'location_lng')
    op.drop_column('reports', 'location_lat')

    # 2. Revert AlertLog table
    op.drop_column('alert_logs', 'location_lng')
    op.drop_column('alert_logs', 'location_lat')
    op.drop_column('alert_logs', 'is_high_fidelity')
    op.drop_column('alert_logs', 'fidelity_score')
