"""initial_postgres_schema

Revision ID: d4cd4e1834c9
Revises: 
Create Date: 2026-03-18 15:56:07.135387

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4cd4e1834c9'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    # 1. Items
    op.create_table(
        'items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String()),
        sa.Column('content', sa.String()),
        sa.Column('url', sa.String(), unique=True),
        sa.Column('source', sa.String()),
        sa.Column('published_at', sa.DateTime(timezone=True)),
        sa.Column('normalized_content', sa.String()),
        sa.Column('entities', sa.JSON()), # Will be JSONB in Postgres
        sa.Column('category', sa.String()),
        sa.Column('cluster_id', postgresql.UUID(as_uuid=True)),
        sa.Column('intensity_score', sa.Float()),
        sa.Column('risk_score', sa.Float()),
        sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 2. Reports
    op.create_table(
        'reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String()),
        sa.Column('summary', sa.String()),
        sa.Column('full_markdown', sa.String()),
        sa.Column('category', sa.String()),
        sa.Column('metadata_json', postgresql.JSONB()),
        sa.Column('substack_slug', sa.String(), unique=True),
        sa.Column('substack_draft_url', sa.String()),
        sa.Column('substack_published_url', sa.String()),
        sa.Column('substack_post_status', sa.String()),
        sa.Column('substack_post_id', sa.String()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 3. External Posts
    op.create_table(
        'external_posts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('platform', sa.String()),
        sa.Column('external_id', sa.String()),
        sa.Column('content_preview', sa.String()),
        sa.Column('url', sa.String()),
        sa.Column('related_report_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('reports.id', ondelete='SET NULL')),
        sa.Column('posted_at', sa.DateTime(timezone=True)),
        sa.Column('metrics', postgresql.JSONB())
    )

    # 4. Risk Headlining
    op.create_table(
        'risk_headlining',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('cluster_id', sa.String(), unique=True),
        sa.Column('headline_en', sa.String()),
        sa.Column('headline_jp', sa.String()),
        sa.Column('impact_score', sa.Float()),
        sa.Column('geopolitical_context', sa.String()),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 5. Trend Signals
    op.create_table(
        'trend_signals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('topic', sa.String()),
        sa.Column('pattern_name', sa.String()),
        sa.Column('intensity', sa.Float()),
        sa.Column('summary', sa.String()),
        sa.Column('supporting_clusters', postgresql.JSONB()),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 6. Alert Logs
    op.create_table(
        'alert_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('trigger_type', sa.String()), # NewPattern, IntensitySpike, DomainDiversity
        sa.Column('severity', sa.String(), server_default='watch'),
        sa.Column('topic', sa.String()),
        sa.Column('message', sa.String()),
        sa.Column('feedback_score', sa.Integer()),
        sa.Column('related_report_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('reports.id', ondelete='SET NULL')),
        sa.Column('intelligence_score', sa.Float()),
        sa.Column('suppressed', sa.Boolean(), server_default='false'),
        sa.Column('metadata_json', postgresql.JSONB()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 7. Analyst Profiles
    op.create_table(
        'analyst_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('telegram_chat_id', sa.String(), unique=True, nullable=False),
        sa.Column('hashed_password', sa.String()),
        sa.Column('user_role', sa.String(), server_default='analyst'),
        sa.Column('watch_keywords', postgresql.JSONB()),
        sa.Column('watch_entities', postgresql.JSONB()),
        sa.Column('watch_sectors', postgresql.JSONB()),
        sa.Column('min_severity_threshold', sa.String(), server_default='watch'),
        sa.Column('min_intelligence_threshold', sa.Float(), server_default='0.35'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 8. Alert Deliveries
    op.create_table(
        'alert_deliveries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('alert_log_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('alert_logs.id', ondelete='CASCADE')),
        sa.Column('analyst_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('analyst_profiles.id', ondelete='CASCADE')),
        sa.Column('status', sa.String()),
        sa.Column('relevance_score', sa.Float()),
        sa.Column('suppression_reason', sa.String()),
        sa.Column('delivered_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 9. Session Revocations
    op.create_table(
        'session_revocations',
        sa.Column('session_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('revoked', sa.Boolean(), server_default='false'),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.Column('reason', sa.String())
    )

    # 10. Security Logs
    op.create_table(
        'security_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True)),
        sa.Column('session_id', postgresql.UUID(as_uuid=True)),
        sa.Column('details', postgresql.JSONB()),
        sa.Column('client_ip', sa.String()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )


def downgrade() -> None:
    op.drop_table('security_logs')
    op.drop_table('session_revocations')
    op.drop_table('alert_deliveries')
    op.drop_table('analyst_profiles')
    op.drop_table('alert_logs')
    op.drop_table('trend_signals')
    op.drop_table('risk_headlining')
    op.drop_table('external_posts')
    op.drop_table('reports')
    op.drop_table('items')
