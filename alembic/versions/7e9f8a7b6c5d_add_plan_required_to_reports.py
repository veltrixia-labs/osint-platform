"""add plan_required to reports

Revision ID: 7e9f8a7b6c5d
Revises: 1b27abef1903
Create Date: 2026-03-24 02:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7e9f8a7b6c5d'
down_revision = '1b27abef1903'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add column as nullable first to allow backfill
    op.add_column('reports', sa.Column('plan_required', sa.String(), nullable=True, server_default='free'))

    # 2. Backfill existing data
    # daily -> free
    # weekly -> pro
    # monthly -> experts
    op.execute("UPDATE reports SET plan_required = 'free' WHERE report_type = 'daily'")
    op.execute("UPDATE reports SET plan_required = 'pro' WHERE report_type = 'weekly'")
    op.execute("UPDATE reports SET plan_required = 'experts' WHERE report_type = 'monthly'")
    
    # 3. Handle cases where report_type might be null or unknown (optional)
    op.execute("UPDATE reports SET plan_required = 'free' WHERE plan_required IS NULL")

    # 4. Make it non-nullable if desired (Postgres specific check needed for SQLite compatibility)
    # Since we want to be safe, we use batch_alter_table which works for both
    with op.batch_alter_table('reports') as batch_op:
        batch_op.alter_column('plan_required', nullable=False)


def downgrade():
    op.drop_column('reports', 'plan_required')
