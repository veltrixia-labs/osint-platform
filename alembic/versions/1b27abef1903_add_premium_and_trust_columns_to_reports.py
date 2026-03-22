"""Add premium and trust columns to reports

Revision ID: 1b27abef1903
Revises: ed1741ec37e1
Create Date: 2026-03-22 10:34:31.140872

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b27abef1903'
down_revision: Union[str, Sequence[str], None] = 'ed1741ec37e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('reports', sa.Column('is_premium', sa.Boolean(), nullable=True, server_default=sa.text('false')))
    op.add_column('reports', sa.Column('source_count', sa.Integer(), nullable=True, server_default=sa.text('0')))
    op.add_column('reports', sa.Column('confidence_level', sa.String(), nullable=True, server_default=sa.text("'Low'")))

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('reports', 'confidence_level')
    op.drop_column('reports', 'source_count')
    op.drop_column('reports', 'is_premium')
