"""add created_at indexes for performance

Revision ID: bdf0d08f0ffd
Revises: 85a3a5d4024c
Create Date: 2026-03-24 11:16:32.358604

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bdf0d08f0ffd'
down_revision: Union[str, Sequence[str], None] = '85a3a5d4024c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Adding indexes on created_at for performance in sort/cleanup operations
    op.create_index('ix_raw_items_created_at', 'raw_items', ['created_at'], unique=False)
    op.create_index('ix_items_created_at', 'items', ['created_at'], unique=False)
    op.create_index('ix_alert_logs_triggered_at', 'alert_logs', ['triggered_at'], unique=False)
    op.create_index('ix_reports_created_at', 'reports', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_reports_created_at', table_name='reports')
    op.drop_index('ix_alert_logs_triggered_at', table_name='alert_logs')
    op.drop_index('ix_items_created_at', table_name='items')
    op.drop_index('ix_raw_items_created_at', table_name='raw_items')
