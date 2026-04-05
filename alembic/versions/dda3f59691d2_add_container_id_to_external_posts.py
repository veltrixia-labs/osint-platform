"""add_container_id_to_external_posts

Revision ID: dda3f59691d2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-05 16:53:49.666323

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dda3f59691d2'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add container_id to external_posts.

    Threads uses a 2-step publish flow:
      1. Create a container  -> returns container_id
      2. Publish the container -> returns media_id (stored in external_id)
    report_generator.py writes container_id; this column was previously missing
    from the model, causing the value to be silently discarded.
    """
    op.add_column(
        'external_posts',
        sa.Column('container_id', sa.String(), nullable=True)
    )


def downgrade() -> None:
    """Remove container_id from external_posts."""
    with op.batch_alter_table('external_posts') as batch_op:
        batch_op.drop_column('container_id')
