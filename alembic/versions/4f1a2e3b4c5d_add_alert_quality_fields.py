"""Add alert quality and system-wide visibility fields

Revision ID: 4f1a2e3b4c5d
Revises: ed1741ec37e1, bdf0d08f0ffd
Create Date: 2026-03-25 10:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4f1a2e3b4c5d'
down_revision: Union[str, Sequence[str], None] = ('ed1741ec37e1', 'bdf0d08f0ffd')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Add columns with server_default to handle existing data
    op.add_column('alert_logs', sa.Column('status', sa.String(), nullable=True, server_default='pending_evidence'))
    op.add_column('alert_logs', sa.Column('is_system_wide', sa.Boolean(), nullable=True, server_default='1'))
    op.add_column('alert_logs', sa.Column('supporting_events_count', sa.Integer(), nullable=True, server_default='0'))

def downgrade() -> None:
    op.drop_column('alert_logs', 'supporting_events_count')
    op.drop_column('alert_logs', 'is_system_wide')
    op.drop_column('alert_logs', 'status')
