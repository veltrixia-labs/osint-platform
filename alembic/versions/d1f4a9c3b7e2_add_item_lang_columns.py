"""add items.title_original and items.lang for multilingual pilot (C-4)

Revision ID: d1f4a9c3b7e2
Revises: c8a2f5d7e9b1
Create Date: 2026-06-09 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1f4a9c3b7e2'
down_revision: Union[str, Sequence[str], None] = 'c8a2f5d7e9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive, nullable-only. Existing rows get NULL. No backfill, no default.
    op.add_column('items', sa.Column('title_original', sa.String(), nullable=True))
    op.add_column('items', sa.Column('lang', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('items', 'lang')
    op.drop_column('items', 'title_original')
