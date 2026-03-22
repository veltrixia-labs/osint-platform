"""Add title and teaser_md to reports

Revision ID: 3d9e8f7a6b2c
Revises: 2c8d9e7f4b1a
Create Date: 2026-03-22 14:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3d9e8f7a6b2c'
down_revision: Union[str, Sequence[str], None] = '2c8d9e7f4b1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('reports', sa.Column('title', sa.String(), nullable=True))
    op.add_column('reports', sa.Column('teaser_md', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('reports', 'teaser_md')
    op.drop_column('reports', 'title')
