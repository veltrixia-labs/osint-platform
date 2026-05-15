"""add_bea_gdp_by_industry

Revision ID: ce69929fa098
Revises: f6c4d2e1b0a8
Create Date: 2026-05-04 14:46:49.074900

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce69929fa098'
down_revision: Union[str, Sequence[str], None] = 'f6c4d2e1b0a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the bea_gdp_by_industry table."""
    op.create_table('bea_gdp_by_industry',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('dataset_name', sa.String(length=64), nullable=False),
        sa.Column('table_id', sa.String(length=16), nullable=False),
        sa.Column('frequency', sa.String(length=4), nullable=False),
        sa.Column('year', sa.String(length=8), nullable=False),
        sa.Column('quarter', sa.String(length=8), nullable=False),
        sa.Column('industry', sa.String(length=16), nullable=False),
        sa.Column('industry_description', sa.String(length=256), nullable=True),
        sa.Column('data_value', sa.Float(), nullable=True),
        sa.Column('note_ref', sa.String(length=32), nullable=True),
        sa.Column('note_text', sa.Text(), nullable=True),
        sa.Column('statistic', sa.String(length=128), nullable=True),
        sa.Column('utc_production_time', sa.String(length=32), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('raw_json', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dataset_name', 'table_id', 'frequency', 'year', 'quarter', 'industry', name='uq_bea_gdp_data_point')
    )
    op.create_index('ix_bea_gdp_fetched_at', 'bea_gdp_by_industry', ['fetched_at'], unique=False)
    op.create_index('ix_bea_gdp_year_industry', 'bea_gdp_by_industry', ['year', 'industry'], unique=False)


def downgrade() -> None:
    """Drop the bea_gdp_by_industry table."""
    op.drop_index('ix_bea_gdp_year_industry', table_name='bea_gdp_by_industry')
    op.drop_index('ix_bea_gdp_fetched_at', table_name='bea_gdp_by_industry')
    op.drop_table('bea_gdp_by_industry')
