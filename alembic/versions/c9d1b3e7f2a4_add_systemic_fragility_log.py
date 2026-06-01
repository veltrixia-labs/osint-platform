"""Add systemic_fragility_log table

Revision ID: c9d1b3e7f2a4
Revises: a7f4c2d9e1b6
Create Date: 2026-05-26 10:00:00.000000

Persists the SystemicFragilityEngine output (entropy + kinematic viscosity)
per domain per pipeline cycle so the dashboard can render the 2D phase-space
trajectory and the historical API can serve `/pro/domains/{id}/fragility-history`.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c9d1b3e7f2a4'
down_revision: Union[str, Sequence[str], None] = 'a7f4c2d9e1b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'systemic_fragility_log',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('domain_id', sa.String(length=64), nullable=False),
        sa.Column(
            'timestamp',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column('entropy_index', sa.Float(), nullable=False),
        sa.Column('viscosity_coefficient', sa.Float(), nullable=False),
        sa.Column('label', sa.String(length=64), nullable=False),
        sa.Column('phase_transition_warning', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sample_size', sa.Integer(), nullable=True),
        sa.Column('raw_payload', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_systemic_fragility_log_domain_id', 'systemic_fragility_log', ['domain_id'])
    op.create_index('ix_systemic_fragility_log_timestamp', 'systemic_fragility_log', ['timestamp'])
    op.create_index('ix_sfl_domain_timestamp', 'systemic_fragility_log', ['domain_id', 'timestamp'])


def downgrade() -> None:
    op.drop_index('ix_sfl_domain_timestamp', table_name='systemic_fragility_log')
    op.drop_index('ix_systemic_fragility_log_timestamp', table_name='systemic_fragility_log')
    op.drop_index('ix_systemic_fragility_log_domain_id', table_name='systemic_fragility_log')
    op.drop_table('systemic_fragility_log')
