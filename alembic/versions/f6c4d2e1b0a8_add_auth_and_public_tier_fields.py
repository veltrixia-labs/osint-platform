"""add auth and public tier fields

Revision ID: f6c4d2e1b0a8
Revises: bdf0d08f0ffd
Create Date: 2026-04-07 18:50:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6c4d2e1b0a8'
down_revision: Union[str, Sequence[str], None] = 'bdf0d08f0ffd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add auth related columns to analyst_profiles
    op.add_column('analyst_profiles', sa.Column('email', sa.String(), nullable=True))
    op.add_column('analyst_profiles', sa.Column('is_email_verified', sa.Boolean(), server_default='false', nullable=True))
    op.add_column('analyst_profiles', sa.Column('hashed_password', sa.String(), nullable=True))
    op.add_column('analyst_profiles', sa.Column('is_active', sa.Boolean(), server_default='true', nullable=True))
    
    # Create unique constraint for email
    op.create_unique_constraint('uq_analyst_profile_email', 'analyst_profiles', ['email'])


def downgrade() -> None:
    op.drop_constraint('uq_analyst_profile_email', 'analyst_profiles', type_='unique')
    op.drop_column('analyst_profiles', 'is_active')
    op.drop_column('analyst_profiles', 'hashed_password')
    op.drop_column('analyst_profiles', 'is_email_verified')
    op.drop_column('analyst_profiles', 'email')
