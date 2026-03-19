"""Restore topic columns to alert_logs and trend_signals

Revision ID: ed1741ec37e1
Revises: 546c64d1a7fb
Create Date: 2026-03-19 04:28:31.994424

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed1741ec37e1'
down_revision: Union[str, Sequence[str], None] = '546c64d1a7fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('alert_logs', sa.Column('topic', sa.String(), nullable=True))
    op.add_column('trend_signals', sa.Column('topic', sa.String(), nullable=True))

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('trend_signals', 'topic')
    op.drop_column('alert_logs', 'topic')
    # ### end Alembic commands ###
