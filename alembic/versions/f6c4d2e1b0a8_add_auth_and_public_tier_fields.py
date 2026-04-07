"""add auth and public tier fields (CLEANUP VERSION)

Revision ID: f6c4d2e1b0a8
Revises: bdf0d08f0ffd
Create Date: 2026-04-07 18:50:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6c4d2e1b0a8'
down_revision: Union[str, Sequence[str], None] = 'dda3f59691d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Force Cleanup Phase ──────────────────────────────────────────────────
    # We drop any existing overlapping columns to ensure a clean state
    # as the environment has drifted or partially updated.
    
    conn = op.get_bind()
    # Check if we are on postgres to use IF EXISTS
    if conn.engine.name == 'postgresql':
        op.execute("ALTER TABLE analyst_profiles DROP COLUMN IF EXISTS hashed_password CASCADE")
        op.execute("ALTER TABLE analyst_profiles DROP COLUMN IF EXISTS is_email_verified CASCADE")
        op.execute("ALTER TABLE analyst_profiles DROP COLUMN IF EXISTS is_active CASCADE")
        op.execute("ALTER TABLE analyst_profiles DROP COLUMN IF EXISTS email CASCADE")
    else:
        # Generic fallback if needed (usually dev/sqlite)
        # Note: SQLite doesn't support DROP COLUMN easily before 3.35+
        pass

    # ── Re-creation Phase ────────────────────────────────────────────────────
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
