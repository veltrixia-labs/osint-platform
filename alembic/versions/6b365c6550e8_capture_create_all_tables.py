"""capture the three tables that exist only because of a create_all

Revision ID: 6b365c6550e8
Revises: b4e1c7a2f9d3
Create Date: 2026-10-06 00:00:00.000000

WHY. `analytics_events`, `stripe_events` and `system_metrics` are used by the running
application (the scheduler heartbeat, Stripe webhook idempotency, the analytics endpoint), but
no migration ever created them. Production has them because an unconditional
`Base.metadata.create_all` ran at startup during a window in March 2026 (b5bc43e..e473e93,
inferred, not confirmed from Render's deploy log). A database built from migrations alone had 44
tables to production's 47. Vault audit §12.53.

WHAT THIS DOES, BY CASE (checked per table, independently):
  * table ABSENT   -> create it exactly as production has it (empty DB, new environment, DR).
  * table PRESENT and its shape MATCHES the spec below -> do nothing (production today).
  * table PRESENT with a DIFFERENT shape -> RAISE, naming every difference. The migration
    aborts and its transaction rolls back. This is deliberate: a silent skip would mark the
    revision applied over a table that does not match what the code and this file describe.
    CREATE TABLE IF NOT EXISTS, or a bare existence check, would be silent in exactly this case.

THE SPEC IS FROZEN HERE, NOT IMPORTED FROM db/models.py. It was read from PRODUCTION on
2026-10-06 (information_schema + pg_catalog, read-only session). It was then diffed against
`Base.metadata` from today's models: identical for all three tables in columns, types,
nullability, defaults, constraint names and index names. A migration must not change meaning
when the ORM is edited later.

DOWNGRADE DOES NOT DROP ANYTHING. On production these tables predate this revision, which only
records them. Dropping them would destroy live data (system_metrics: the heartbeat history,
192,330 updates as of 2026-10-06). A downgrade past this revision leaves the tables in place, and
re-upgrading sees them, verifies the shape and skips.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6b365c6550e8'
down_revision: Union[str, Sequence[str], None] = 'b4e1c7a2f9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Expected shape, as measured on production 2026-10-06 ────────────────────────────────────
# columns: name -> (type family, nullable, server_default or None)
# type family is matched on the SQLAlchemy type class the inspector reports.
_SPEC = {
    'analytics_events': {
        'columns': {
            'id':            ('UUID', False, None),
            'event_type':    ('VARCHAR', False, None),
            'report_id':     ('UUID', True, None),
            'user_id':       ('UUID', True, None),
            'metadata_json': ('JSON', True, None),
            'created_at':    ('TIMESTAMP_TZ', True, 'now()'),
        },
        'pk': ['id'],
        'unique': {},
        'fks': {  # (local cols) -> (referred table, referred cols, ondelete)
            ('report_id',): ('reports', ('id',), 'SET NULL'),
            ('user_id',): ('analyst_profiles', ('id',), 'SET NULL'),
        },
        'indexes': {  # non-constraint indexes: name -> (cols, unique)
            'ix_analytics_events_event_type': (('event_type',), False),
            'ix_analytics_events_report_id': (('report_id',), False),
            'ix_analytics_events_user_id': (('user_id',), False),
            'ix_analytics_events_created_at': (('created_at',), False),
        },
    },
    'stripe_events': {
        'columns': {
            'id':           ('UUID', False, None),
            'event_id':     ('VARCHAR', False, None),
            'event_type':   ('VARCHAR', True, None),
            'processed_at': ('TIMESTAMP_TZ', True, 'now()'),
        },
        'pk': ['id'],
        'unique': {'uq_stripe_event_id': ('event_id',)},
        'fks': {},
        'indexes': {
            'ix_stripe_events_event_id': (('event_id',), False),
        },
    },
    'system_metrics': {
        'columns': {
            'metric_key':   ('VARCHAR', False, None),
            'metric_value': ('VARCHAR', True, None),
            'updated_at':   ('TIMESTAMP_TZ', True, 'now()'),
        },
        'pk': ['metric_key'],
        'unique': {},
        'fks': {},
        'indexes': {},
    },
}


def _family(t) -> str:
    if isinstance(t, sa.TIMESTAMP) or isinstance(t, sa.DateTime):
        return 'TIMESTAMP_TZ' if getattr(t, 'timezone', False) else 'TIMESTAMP'
    if isinstance(t, (postgresql.UUID, sa.Uuid)):
        return 'UUID'
    if isinstance(t, (postgresql.JSONB,)):
        return 'JSONB'
    if isinstance(t, sa.JSON):
        return 'JSON'
    if isinstance(t, sa.String) and getattr(t, 'length', None) is None:
        return 'VARCHAR'
    return type(t).__name__ + (f'({t.length})' if getattr(t, 'length', None) else '')


def _norm_default(d):
    if d is None:
        return None
    return str(d).strip().lower()


def _shape_differences(insp, table: str) -> list:
    spec = _SPEC[table]
    diffs = []

    cols = {c['name']: c for c in insp.get_columns(table)}
    for name, (fam, nullable, default) in spec['columns'].items():
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
    for extra in sorted(set(cols) - set(spec['columns'])):
        diffs.append(f'unexpected column {extra}')

    pk = insp.get_pk_constraint(table).get('constrained_columns') or []
    if list(pk) != spec['pk']:
        diffs.append(f'primary key {pk} != {spec["pk"]}')

    uniq = {u['name']: tuple(u['column_names']) for u in insp.get_unique_constraints(table)}
    if uniq != spec['unique']:
        diffs.append(f'unique constraints {uniq} != {spec["unique"]}')

    fks = {}
    for fk in insp.get_foreign_keys(table):
        fks[tuple(fk['constrained_columns'])] = (
            fk['referred_table'], tuple(fk['referred_columns']),
            (fk.get('options') or {}).get('ondelete'))
    if fks != spec['fks']:
        diffs.append(f'foreign keys {fks} != {spec["fks"]}')

    # Indexes backing a UNIQUE constraint are reported by some dialect versions; they are
    # covered by the unique-constraint check above, so exclude them here.
    idx = {i['name']: (tuple(i['column_names']), bool(i['unique']))
           for i in insp.get_indexes(table)
           if i['name'] not in spec['unique'] and not i.get('duplicates_constraint')}
    if idx != spec['indexes']:
        diffs.append(f'indexes {idx} != {spec["indexes"]}')
    return diffs


def _create(table: str) -> None:
    if table == 'analytics_events':
        op.create_table(
            'analytics_events',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('event_type', sa.String(), nullable=False),
            sa.Column('report_id', sa.UUID(), nullable=True),
            sa.Column('user_id', sa.UUID(), nullable=True),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['report_id'], ['reports.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['user_id'], ['analyst_profiles.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_analytics_events_event_type', 'analytics_events', ['event_type'], unique=False)
        op.create_index('ix_analytics_events_report_id', 'analytics_events', ['report_id'], unique=False)
        op.create_index('ix_analytics_events_user_id', 'analytics_events', ['user_id'], unique=False)
        op.create_index('ix_analytics_events_created_at', 'analytics_events', ['created_at'], unique=False)
    elif table == 'stripe_events':
        op.create_table(
            'stripe_events',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('event_id', sa.String(), nullable=False),
            sa.Column('event_type', sa.String(), nullable=True),
            sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('event_id', name='uq_stripe_event_id'),
        )
        op.create_index('ix_stripe_events_event_id', 'stripe_events', ['event_id'], unique=False)
    elif table == 'system_metrics':
        op.create_table(
            'system_metrics',
            sa.Column('metric_key', sa.String(), nullable=False),
            sa.Column('metric_value', sa.String(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.PrimaryKeyConstraint('metric_key'),
        )
    else:  # pragma: no cover
        raise ValueError(table)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing = set(insp.get_table_names())
    problems = {}
    for table in ('system_metrics', 'stripe_events', 'analytics_events'):
        if table not in existing:
            continue
        d = _shape_differences(insp, table)
        if d:
            problems[table] = d
    if problems:
        # Fail BEFORE creating anything, so a mismatch never leaves a half-applied revision.
        lines = [f'{t}: ' + '; '.join(d) for t, d in problems.items()]
        raise RuntimeError(
            '6b365c6550e8: existing table(s) do not match the shape this migration records. '
            'Refusing to mark the revision applied over a mismatched schema:\n  ' + '\n  '.join(lines))
    for table in ('system_metrics', 'stripe_events', 'analytics_events'):
        if table not in existing:
            _create(table)


def downgrade() -> None:
    # Deliberately does NOT drop the tables; see the module docstring. On production they
    # predate this revision and hold live data.
    pass
