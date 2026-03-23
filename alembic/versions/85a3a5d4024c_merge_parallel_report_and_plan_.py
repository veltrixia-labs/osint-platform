"""Merge parallel report and plan migrations

Revision ID: 85a3a5d4024c
Revises: 3d9e8f7a6b2c, 7e9f8a7b6c5d
Create Date: 2026-03-24 03:30:03.442481

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '85a3a5d4024c'
down_revision: Union[str, Sequence[str], None] = ('3d9e8f7a6b2c', '7e9f8a7b6c5d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
