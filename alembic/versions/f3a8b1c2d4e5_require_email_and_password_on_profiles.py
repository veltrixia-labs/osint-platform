"""require email and hashed_password on analyst_profiles

Revision ID: f3a8b1c2d4e5
Revises: e7b2c9d4f1a0
Create Date: 2026-05-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a8b1c2d4e5"
down_revision: Union[str, Sequence[str], None] = "e7b2c9d4f1a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        """
        UPDATE analyst_profiles
        SET email = LOWER(telegram_chat_id) || '@legacy.veltrixia.local'
        WHERE email IS NULL AND telegram_chat_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE analyst_profiles
        SET email = 'orphan-' || REPLACE(id::text, '-', '') || '@legacy.veltrixia.local'
        WHERE email IS NULL
        """
    )

    from sqlalchemy import text

    if bind.dialect.name == "postgresql":
        from argon2 import PasswordHasher

        placeholder_hash = PasswordHasher().hash("legacy-placeholder-change-me")
        bind.execute(
            text(
                "UPDATE analyst_profiles SET hashed_password = :hp WHERE hashed_password IS NULL"
            ),
            {"hp": placeholder_hash},
        )
    else:
        bind.execute(
            text(
                "UPDATE analyst_profiles SET hashed_password = 'legacy' WHERE hashed_password IS NULL"
            )
        )

    op.alter_column("analyst_profiles", "email", existing_type=sa.String(), nullable=False)
    op.alter_column(
        "analyst_profiles",
        "hashed_password",
        existing_type=sa.String(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column("analyst_profiles", "hashed_password", nullable=True)
    op.alter_column("analyst_profiles", "email", nullable=True)
