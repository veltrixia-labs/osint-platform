"""Add COT reports table and sanctions/network fields on Stakeholder

Revision ID: a7f4c2d9e1b6
Revises: f3a8b1c2d4e5
Create Date: 2026-05-25 12:00:00.000000

Day 1 of the institutional macro sprint. Two changes:

1. ``cot_reports`` — weekly CFTC Commitments of Traders snapshot.
   Unique key (market_and_exchange, report_date) supports idempotent ingestion.

2. ``stakeholders`` extensions: OpenSanctions linkage + sanctioned status +
   PEP score + pre-computed PageRank score for the Collateral Damage map.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'a7f4c2d9e1b6'
down_revision: Union[str, Sequence[str], None] = 'f3a8b1c2d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. cot_reports ---------------------------------------------------
    op.create_table(
        'cot_reports',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('market_and_exchange', sa.String(), nullable=False),
        sa.Column('report_date', sa.DateTime(timezone=False), nullable=False),
        sa.Column('yyyy_report_week_ww', sa.String(), nullable=True),
        sa.Column('open_interest_all', sa.Integer(), nullable=True),
        sa.Column('noncomm_long', sa.Integer(), nullable=True),
        sa.Column('noncomm_short', sa.Integer(), nullable=True),
        sa.Column('noncomm_spread', sa.Integer(), nullable=True),
        sa.Column('comm_long', sa.Integer(), nullable=True),
        sa.Column('comm_short', sa.Integer(), nullable=True),
        sa.Column('nonrept_long', sa.Integer(), nullable=True),
        sa.Column('nonrept_short', sa.Integer(), nullable=True),
        sa.Column('raw_json', sa.JSON(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('market_and_exchange', 'report_date', name='uq_cot_market_date'),
    )
    op.create_index('ix_cot_reports_market_and_exchange', 'cot_reports', ['market_and_exchange'])
    op.create_index('ix_cot_reports_report_date', 'cot_reports', ['report_date'])

    # --- 2. stakeholders sanctions / PageRank extensions ------------------
    with op.batch_alter_table('stakeholders') as batch:
        batch.add_column(sa.Column('opensanctions_id', sa.String(), nullable=True))
        batch.add_column(sa.Column('sanctioned_status', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('sanction_program', sa.String(), nullable=True))
        batch.add_column(sa.Column('pep_score', sa.Float(), nullable=True))
        batch.add_column(sa.Column('network_score', sa.Float(), nullable=False, server_default='0.0'))
    op.create_index('ix_stakeholders_opensanctions_id', 'stakeholders', ['opensanctions_id'])


def downgrade() -> None:
    op.drop_index('ix_stakeholders_opensanctions_id', table_name='stakeholders')
    with op.batch_alter_table('stakeholders') as batch:
        batch.drop_column('network_score')
        batch.drop_column('pep_score')
        batch.drop_column('sanction_program')
        batch.drop_column('sanctioned_status')
        batch.drop_column('opensanctions_id')

    op.drop_index('ix_cot_reports_report_date', table_name='cot_reports')
    op.drop_index('ix_cot_reports_market_and_exchange', table_name='cot_reports')
    op.drop_table('cot_reports')
