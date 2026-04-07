"""merge remaining heads

Revision ID: f9a2b7c6d5e1
Revises: f6c4d2e1b0a8, dda3f59691d2, 2c8d9e7f4b1a
Create Date: 2026-04-07 18:58:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9a2b7c6d5e1'
down_revision: Union[str, Sequence[str], None] = ('f6c4d2e1b0a8', 'dda3f59691d2', '2c8d9e7f4b1a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge heads."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
