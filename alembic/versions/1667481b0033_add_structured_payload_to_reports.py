"""add_structured_payload_to_reports

Revision ID: 1667481b0033
Revises: 63459c302658
Create Date: 2026-05-11 14:51:30.317830

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1667481b0033'
down_revision: Union[str, Sequence[str], None] = '63459c302658'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reports', sa.Column('structured_payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))


def downgrade() -> None:
    op.drop_column('reports', 'structured_payload')
