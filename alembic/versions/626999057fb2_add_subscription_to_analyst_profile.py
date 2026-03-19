"""add_subscription_to_analyst_profile

Revision ID: 626999057fb2
Revises: d4cd4e1834c9
Create Date: 2026-03-18 16:20:39.469235

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '626999057fb2'
down_revision: Union[str, Sequence[str], None] = 'd4cd4e1834c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('analyst_profiles', sa.Column('subscription_tier', sa.String(), nullable=True, server_default='free'))
    op.add_column('analyst_profiles', sa.Column('subscription_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('analyst_profiles', 'subscription_expires_at')
    op.drop_column('analyst_profiles', 'subscription_tier')
