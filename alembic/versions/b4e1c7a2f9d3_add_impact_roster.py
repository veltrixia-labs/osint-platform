"""add_impact_roster

Revision ID: b4e1c7a2f9d3
Revises: a7c1e4b9d2f3
Create Date: 2026-07-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b4e1c7a2f9d3'
down_revision: Union[str, Sequence[str], None] = 'a7c1e4b9d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'impact_roster_loads',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('source_dir', sa.Text(), nullable=False),
        sa.Column('impacts_sha256', sa.Text(), nullable=True),
        sa.Column('pd_sha256', sa.Text(), nullable=True),
        sa.Column('pd_source_as_of', sa.Text(), nullable=True),
        sa.Column('scenarios_seen', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('scenarios_loaded', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('scenarios_skipped', sa.Text(), nullable=True),
        sa.Column('rows_written', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'impact_roster_rows',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('load_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('scenario', sa.Text(), nullable=False),
        sa.Column('scenario_kind', sa.Text(), nullable=False),
        sa.Column('entity', sa.Text(), nullable=False),
        sa.Column('entity_kind', sa.Text(), nullable=False),
        sa.Column('impact', sa.Float(), nullable=False),
        sa.Column('pd', sa.Float(), nullable=True),
        sa.Column('pd_status', sa.Text(), nullable=True),
        sa.Column('pd_category', sa.Text(), nullable=True),
        sa.Column('pd_reason', sa.Text(), nullable=True),
        sa.Column('asset_value', sa.Float(), nullable=True),
        sa.Column('debt', sa.Float(), nullable=True),
        sa.Column('sigma', sa.Float(), nullable=True),
        sa.Column('d2', sa.Float(), nullable=True),
        sa.Column('bucket', sa.Text(), nullable=True),
        sa.Column('pd_source_as_of', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_impact_roster_rows_load_id', 'impact_roster_rows', ['load_id'], unique=False)
    op.create_index('ix_impact_roster_rows_scenario', 'impact_roster_rows', ['scenario'], unique=False)
    op.create_index('ix_impact_roster_rows_entity', 'impact_roster_rows', ['entity'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_impact_roster_rows_entity', table_name='impact_roster_rows')
    op.drop_index('ix_impact_roster_rows_scenario', table_name='impact_roster_rows')
    op.drop_index('ix_impact_roster_rows_load_id', table_name='impact_roster_rows')
    op.drop_table('impact_roster_rows')
    op.drop_table('impact_roster_loads')
