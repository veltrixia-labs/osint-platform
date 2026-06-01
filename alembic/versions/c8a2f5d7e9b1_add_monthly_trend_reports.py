"""Add monthly_trend_reports archival table (Monthly Trend Flow)

Revision ID: c8a2f5d7e9b1
Revises: b7e1c9d4a2f0
Create Date: 2026-05-30 00:00:00.000000

Dedicated archival table for the Monthly Trend Flow feature. One row per
calendar month stores a precomputed flow/network snapshot (nodes + edges +
summary) as JSONB so historical reports load in O(1) with no recalculation.
Rows are archival — never purged by the 24h alert/contagion retention jobs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c8a2f5d7e9b1'
down_revision: Union[str, Sequence[str], None] = 'b7e1c9d4a2f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'monthly_trend_reports',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('period_year', sa.Integer(), nullable=False),
        sa.Column('period_month', sa.Integer(), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('schema_version', sa.String(), nullable=True),
        sa.Column('nodes_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('edges_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('summary_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('alerts_total', sa.Integer(), nullable=True),
        sa.Column('alerts_spiked', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('period_year', 'period_month', name='uq_monthly_trend_period'),
    )
    op.create_index(
        'ix_monthly_trend_period',
        'monthly_trend_reports',
        ['period_year', 'period_month'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_monthly_trend_period', table_name='monthly_trend_reports')
    op.drop_table('monthly_trend_reports')
