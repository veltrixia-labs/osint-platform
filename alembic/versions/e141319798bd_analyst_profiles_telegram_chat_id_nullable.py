"""analyst_profiles.telegram_chat_id: drop NOT NULL, so signup and Stripe provisioning can create accounts

Revision ID: e141319798bd
Revises: c7d2e4f1a9b3
Create Date: 2026-10-09 00:00:00.000000

WHY. The initial schema (d4cd4e1834c9) created telegram_chat_id as NOT NULL. On 2026-04-08
(aa3f91d) db/models.py made it optional ("legacy / optional"), but no migration on the applied
chain ever relaxed the column; the only one that touches it (63459c302658) does so in its
downgrade(), restoring NOT NULL. Production has it NOT NULL with no default and no trigger.
Neither POST /api/auth/signup (api/main.py) nor Stripe provisioning
(api/stripe_service.py:provision_analyst_for_checkout) sets it, so every new-account INSERT
violates the constraint (vault audit §12.79, §12.80). No account has been created since
2026-03-27.

The unique index analyst_profiles_telegram_chat_id_key stays. It is NULLS DISTINCT
(indnullsnotdistinct = false, measured 2026-10-09), so any number of accounts may hold NULL.

WHAT THIS DOES, BY CASE:
  * column NOT NULL -> drop NOT NULL (metadata-only; the table has 3 rows).
  * column already nullable -> do nothing (a re-upgrade after a manual relax).
  * column ABSENT -> RAISE. The revision is never recorded over a table that does not have
    the column this migration is about.

DOWNGRADE REFUSES ONCE THE COLUMN IS IN USE. Restoring NOT NULL fails on any row holding NULL,
and every account created after this upgrade holds NULL. Rather than fail halfway, downgrade
counts those rows first and raises, naming the count. Making it reversible again means giving
those accounts a value or deleting them, which is a decision about real accounts and is not
taken here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e141319798bd'
down_revision: Union[str, Sequence[str], None] = 'c7d2e4f1a9b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = 'analyst_profiles'
COLUMN = 'telegram_chat_id'


def _column(insp):
    for c in insp.get_columns(TABLE):
        if c['name'] == COLUMN:
            return c
    return None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    col = _column(insp)
    if col is None:
        raise RuntimeError(
            f'e141319798bd: {TABLE}.{COLUMN} does not exist. Refusing to mark the revision '
            'applied over a table without the column it relaxes.')
    if col['nullable']:
        return  # already nullable: nothing to do
    op.alter_column(TABLE, COLUMN, existing_type=sa.VARCHAR(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    nulls = bind.execute(
        sa.text(f'SELECT count(*) FROM {TABLE} WHERE {COLUMN} IS NULL')).scalar() or 0
    if nulls:
        raise RuntimeError(
            f'e141319798bd downgrade: {nulls} row(s) in {TABLE} have {COLUMN} IS NULL; '
            'restoring NOT NULL would fail. Give those accounts a value or delete them first.')
    op.alter_column(TABLE, COLUMN, existing_type=sa.VARCHAR(), nullable=False)
