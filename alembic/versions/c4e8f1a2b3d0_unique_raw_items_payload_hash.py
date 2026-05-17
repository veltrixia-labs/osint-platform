"""unique raw_items payload_hash with duplicate cleanup

Revision ID: c4e8f1a2b3d0
Revises: a9f8c2d1e4b0
Create Date: 2026-05-16

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c4e8f1a2b3d0"
down_revision: Union[str, Sequence[str], None] = "a9f8c2d1e4b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_raw_items_payload_hash_unique"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DELETE FROM raw_items
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY payload_hash
                               ORDER BY created_at ASC NULLS LAST, id ASC
                           ) AS rn
                    FROM raw_items
                ) ranked
                WHERE rn > 1
            )
            """
        )
    else:
        op.execute(
            """
            DELETE FROM raw_items
            WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM raw_items GROUP BY payload_hash
            )
            """
        )
    op.create_index(INDEX_NAME, "raw_items", ["payload_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="raw_items")
