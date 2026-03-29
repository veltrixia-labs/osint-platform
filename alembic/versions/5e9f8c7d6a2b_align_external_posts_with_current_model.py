"""align external_posts with current model

Revision ID: 5e9f8c7d6a2b
Revises: 4f1a2e3b4c5d
Create Date: 2026-03-29 16:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e9f8c7d6a2b'
down_revision: Union[str, Sequence[str], None] = '4f1a2e3b4c5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('external_posts')]
    indexes = [i['name'] for i in inspector.get_indexes('external_posts')]

    with op.batch_alter_table('external_posts', schema=None) as batch_op:
        # 1. Renames (Alignment with models.py)
        if 'related_report_id' in columns and 'report_id' not in columns:
            batch_op.alter_column('related_report_id', new_column_name='report_id')
        
        if 'posted_at' in columns and 'published_at' not in columns:
            batch_op.alter_column('posted_at', new_column_name='published_at')
        
        # 2. Add missing columns
        if 'category' not in columns:
            batch_op.add_column(sa.Column('category', sa.String(), nullable=True))
        
        if 'normalized_theme' not in columns:
            batch_op.add_column(sa.Column('normalized_theme', sa.String(), nullable=True))
        
        if 'status' not in columns:
            batch_op.add_column(sa.Column('status', sa.String(), nullable=True, server_default='success'))
        
        if 'error_message' not in columns:
            batch_op.add_column(sa.Column('error_message', sa.String(), nullable=True))
        
        if 'created_at' not in columns:
            batch_op.add_column(sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
        
        # 3. Add index for novelty checks
        if 'ix_external_posts_normalized_theme' not in indexes:
            batch_op.create_index('ix_external_posts_normalized_theme', ['normalized_theme'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('external_posts')]
    indexes = [i['name'] for i in inspector.get_indexes('external_posts')]

    with op.batch_alter_table('external_posts', schema=None) as batch_op:
        if 'ix_external_posts_normalized_theme' in indexes:
            batch_op.drop_index('ix_external_posts_normalized_theme')
        
        if 'created_at' in columns:
            batch_op.drop_column('created_at')
        if 'error_message' in columns:
            batch_op.drop_column('error_message')
        if 'status' in columns:
            batch_op.drop_column('status')
        if 'normalized_theme' in columns:
            batch_op.drop_column('normalized_theme')
        if 'category' in columns:
            batch_op.drop_column('category')
            
        if 'published_at' in columns and 'posted_at' not in columns:
            batch_op.alter_column('published_at', new_column_name='posted_at')
        if 'report_id' in columns and 'related_report_id' not in columns:
            batch_op.alter_column('report_id', new_column_name='related_report_id')
