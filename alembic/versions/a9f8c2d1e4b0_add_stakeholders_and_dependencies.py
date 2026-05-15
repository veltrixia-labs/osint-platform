"""add stakeholders and dependencies tables

Revision ID: a9f8c2d1e4b0
Revises: 1667481b0033
Create Date: 2026-05-15

Phase-4 company impact tables were referenced in models but never created in upgrade().
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a9f8c2d1e4b0"
down_revision: Union[str, Sequence[str], None] = "1667481b0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return set(insp.get_table_names())


def upgrade() -> None:
    tables = _table_names()

    if "stakeholders" not in tables:
        op.create_table(
            "stakeholders",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("ticker", sa.String(), nullable=True),
            sa.Column("sector", sa.String(), nullable=True),
            sa.Column("country", sa.String(), nullable=True),
            sa.Column("domain", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("location_lat", sa.Float(), nullable=True),
            sa.Column("location_lng", sa.Float(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("is_auto_provisioned", sa.Boolean(), server_default=sa.text("true"), nullable=True),
            sa.Column("strategic_score", sa.Float(), server_default=sa.text("0.0"), nullable=True),
            sa.Column("hit_count", sa.Integer(), server_default=sa.text("0"), nullable=True),
            sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_stakeholders_ticker"), "stakeholders", ["ticker"], unique=False)

    tables = _table_names()

    if "dependencies" not in tables:
        op.create_table(
            "dependencies",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("dependency_type", sa.String(), nullable=True),
            sa.Column("exposure_weight", sa.Float(), server_default=sa.text("0.5"), nullable=True),
            sa.Column("beta_correlation", sa.Float(), server_default=sa.text("1.0"), nullable=True),
            sa.Column(
                "substitution_elasticity",
                sa.Float(),
                server_default=sa.text("0.5"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["source_id"], ["stakeholders.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["target_id"], ["stakeholders.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_id", "target_id", name="uq_dependency_pair"),
        )

    tables = _table_names()

    if "predictions" not in tables:
        op.create_table(
            "predictions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("prediction_id", sa.String(), nullable=False),
            sa.Column("trigger_event", sa.Text(), nullable=True),
            sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("predicted_alpha", sa.Float(), nullable=True),
            sa.Column("baseline_index_ticker", sa.String(), server_default="^GSPC", nullable=True),
            sa.Column("time_horizon_days", sa.Integer(), server_default=sa.text("7"), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("is_evaluated", sa.Boolean(), server_default=sa.text("false"), nullable=True),
            sa.Column("actual_alpha", sa.Float(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["target_id"], ["stakeholders.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("prediction_id"),
        )


def downgrade() -> None:
    tables = _table_names()
    if "predictions" in tables:
        op.drop_table("predictions")
    tables = _table_names()
    if "dependencies" in tables:
        op.drop_table("dependencies")
    tables = _table_names()
    if "stakeholders" in tables:
        op.drop_index(op.f("ix_stakeholders_ticker"), table_name="stakeholders")
        op.drop_table("stakeholders")
