"""ingest_rejections: the record of feed entries normalize refused as stale on arrival

Revision ID: c7d2e4f1a9b3
Revises: 6b365c6550e8
Create Date: 2026-10-07 00:00:00.000000

WHY. On 2026-10-07 the first batched retention run deleted six months of raw rows and, with
them, the dedup memory. Feeds still serving old entries were re-ingested as new items
(published 2025-12 .. 2026-09, created that day) and shown to users as today's news (vault audit
§12.66-§12.67). processor/normalize.py now refuses a new item whose published_at is older than
STALE_ON_ARRIVAL_DAYS. A filter that drops items silently would hide a feed whose dates go bad,
so every refusal is recorded here, one row per entry, readable with SQL without a deploy.

WHAT THIS DOES, BY CASE (the discipline of 6b365c6550e8):
  * table ABSENT   -> create it (every environment today).
  * table PRESENT and its shape MATCHES the spec below -> do nothing (a re-upgrade after a
    downgrade, which does not drop it).
  * table PRESENT with a DIFFERENT shape -> RAISE, naming every difference, BEFORE creating
    anything, so the revision is never recorded over a table that does not match.
    CREATE TABLE IF NOT EXISTS, or a bare existence check, would be silent in exactly that case.

THE SPEC IS FROZEN HERE, not imported from db/models.py, so a later ORM edit cannot change what
this migration means. It matches db/models.py IngestRejection as committed with it.

DOWNGRADE DOES NOT DROP THE TABLE. Its rows are the only record of what the filter rejected;
dropping them on a downgrade would destroy the audit trail the table exists to keep. A
re-upgrade sees the table, verifies the shape and skips.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c7d2e4f1a9b3'
down_revision: Union[str, Sequence[str], None] = '6b365c6550e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = 'ingest_rejections'

# columns: name -> (type family, nullable, server_default or None)
_SPEC = {
    'columns': {
        'dedup_key':         ('VARCHAR', False, None),
        'source_id':         ('VARCHAR', True, None),
        'source_url':        ('VARCHAR', True, None),
        'title':             ('VARCHAR', True, None),
        'published_at':      ('TIMESTAMP_TZ', True, None),
        'reason':            ('VARCHAR', False, None),
        'threshold_days':    ('INTEGER', True, None),
        'first_rejected_at': ('TIMESTAMP_TZ', False, 'now()'),
        'last_rejected_at':  ('TIMESTAMP_TZ', False, 'now()'),
    },
    'pk': ['dedup_key'],
    'unique': {},
    'fks': {},
    'indexes': {
        'ix_ingest_rejections_last_rejected_at': (('last_rejected_at',), False),
    },
}


def _family(t) -> str:
    if isinstance(t, (sa.TIMESTAMP, sa.DateTime)):
        return 'TIMESTAMP_TZ' if getattr(t, 'timezone', False) else 'TIMESTAMP'
    if isinstance(t, (postgresql.UUID, sa.Uuid)):
        return 'UUID'
    if isinstance(t, sa.Integer):
        return 'INTEGER'
    if isinstance(t, sa.String) and getattr(t, 'length', None) is None:
        return 'VARCHAR'
    return type(t).__name__ + (f'({t.length})' if getattr(t, 'length', None) else '')


def _norm_default(d):
    return None if d is None else str(d).strip().lower()


def _shape_differences(insp) -> list:
    diffs = []
    cols = {c['name']: c for c in insp.get_columns(TABLE)}
    for name, (fam, nullable, default) in _SPEC['columns'].items():
        c = cols.get(name)
        if c is None:
            diffs.append(f'missing column {name}')
            continue
        if _family(c['type']) != fam:
            diffs.append(f'column {name}: type {_family(c["type"])} != {fam}')
        if bool(c['nullable']) != nullable:
            diffs.append(f'column {name}: nullable {c["nullable"]} != {nullable}')
        if _norm_default(c.get('default')) != _norm_default(default):
            diffs.append(f'column {name}: default {c.get("default")!r} != {default!r}')
    for extra in sorted(set(cols) - set(_SPEC['columns'])):
        diffs.append(f'unexpected column {extra}')
    pk = insp.get_pk_constraint(TABLE).get('constrained_columns') or []
    if list(pk) != _SPEC['pk']:
        diffs.append(f'primary key {pk} != {_SPEC["pk"]}')
    uniq = {u['name']: tuple(u['column_names']) for u in insp.get_unique_constraints(TABLE)}
    if uniq != _SPEC['unique']:
        diffs.append(f'unique constraints {uniq} != {_SPEC["unique"]}')
    fks = {tuple(fk['constrained_columns']): fk['referred_table'] for fk in insp.get_foreign_keys(TABLE)}
    if fks != _SPEC['fks']:
        diffs.append(f'foreign keys {fks} != {_SPEC["fks"]}')
    idx = {i['name']: (tuple(i['column_names']), bool(i['unique']))
           for i in insp.get_indexes(TABLE) if not i.get('duplicates_constraint')}
    if idx != _SPEC['indexes']:
        diffs.append(f'indexes {idx} != {_SPEC["indexes"]}')
    return diffs


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if TABLE in set(insp.get_table_names()):
        diffs = _shape_differences(insp)
        if diffs:
            raise RuntimeError(
                'c7d2e4f1a9b3: existing ingest_rejections does not match the shape this migration '
                'records. Refusing to mark the revision applied over a mismatched table:\n  '
                + '\n  '.join(diffs))
        return  # present and matching: nothing to do
    op.create_table(
        TABLE,
        sa.Column('dedup_key', sa.String(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=True),
        sa.Column('source_url', sa.String(), nullable=True),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('threshold_days', sa.Integer(), nullable=True),
        sa.Column('first_rejected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_rejected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('dedup_key'),
    )
    op.create_index('ix_ingest_rejections_last_rejected_at', TABLE, ['last_rejected_at'], unique=False)


def downgrade() -> None:
    # Deliberately does NOT drop the table; see the module docstring.
    pass
