"""Fix confidence_level type to String

Revision ID: 2c8d9e7f4b1a
Revises: 1b27abef1903
Create Date: 2026-03-22 14:10:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2c8d9e7f4b1a'
down_revision: Union[str, Sequence[str], None] = '1b27abef1903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Safely convert confidence_level to VARCHAR if it was mistakenly created as FLOAT/NUMERIC
    # We use a raw SQL approach for Postgres compatibility with 'USING' clause
    connection = op.get_bind()
    
    # Check if we are on Postgres
    if connection.engine.name == 'postgresql':
        op.execute("ALTER TABLE reports ALTER COLUMN confidence_level TYPE VARCHAR(50) USING confidence_level::TEXT")
        op.execute("UPDATE reports SET confidence_level = 'Low' WHERE confidence_level IS NULL OR confidence_level = '0' OR confidence_level = '0.0'")
    else:
        # SQLite or other fallback (re-create column if needed)
        # Note: In SQLite we might just leave it as it handles dynamic typing, 
        # but for consistency we can try to fix it.
        pass

def downgrade() -> None:
    # No easy way to go back to FLOAT without potentially losing data if it contains "High"
    pass
