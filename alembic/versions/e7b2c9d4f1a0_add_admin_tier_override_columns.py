"""add is_admin and manual_tier to analyst_profiles

Revision ID: e7b2c9d4f1a0
Revises: c4e8f1a2b3d0
Create Date: 2026-05-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7b2c9d4f1a0"
down_revision: Union[str, Sequence[str], None] = "c4e8f1a2b3d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _analyst_profile_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {col["name"] for col in insp.get_columns("analyst_profiles")}


def upgrade() -> None:
    columns = _analyst_profile_columns()

    if "is_admin" not in columns:
        op.add_column(
            "analyst_profiles",
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    if "manual_tier" not in columns:
        op.add_column(
            "analyst_profiles",
            sa.Column("manual_tier", sa.String(), nullable=True),
        )

    op.execute(
        "UPDATE analyst_profiles SET is_admin = true WHERE user_role = 'admin'"
    )


def downgrade() -> None:
    columns = _analyst_profile_columns()
    if "manual_tier" in columns:
        op.drop_column("analyst_profiles", "manual_tier")
    if "is_admin" in columns:
        op.drop_column("analyst_profiles", "is_admin")
