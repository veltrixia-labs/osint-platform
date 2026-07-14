"""spatial: nullable magnitudes + node_type + provenance

Makes the spatial graph able to represent "we never measured this" as distinct
from "we measured this at zero".

  • spatial_nodes.impact_score  : NOT NULL -> NULLABLE
  • spatial_edges.edge_intensity: NOT NULL -> NULLABLE
        A null magnitude must survive the DB boundary. Coercing it to 0.0 records
        the claim "no impact", which is false and is exactly the lie the renderer's
        `exposed_unquantified` class was added to prevent.

  • spatial_nodes.node_type ('epicenter' | 'affected' | 'exposed_unquantified')
        `is_epicenter` is RETAINED for back-compat — the existing engine and readers
        still use it. New writers set both.

  • provenance / join columns: node_id, country, order_level, why, confidence,
    has_unquantified_direct_edge, and on edges: unquantified, source_node_id,
    target_node_id.

Purely ADDITIVE + constraint-relaxing. Nothing is dropped or renamed.

Postgres cost notes (this runs against a NON-EMPTY, live table):
  • DROP NOT NULL is a catalog-only change — O(1), no table rewrite.
  • ADD COLUMN with a non-volatile DEFAULT is O(1) since PG11 — no rewrite.
  So the ACCESS EXCLUSIVE locks are held for microseconds, not a table scan.

Revision ID: a7c1e4b9d2f3
Revises: d1f4a9c3b7e2
Create Date: 2026-07-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7c1e4b9d2f3"
down_revision = "d1f4a9c3b7e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── spatial_nodes ────────────────────────────────────────────────────────
    # Relax the magnitude so null ("unmeasured") is representable.
    op.alter_column(
        "spatial_nodes",
        "impact_score",
        existing_type=sa.Float(),
        nullable=True,
        existing_nullable=False,
    )

    # NOT NULL new columns carry a server_default so existing rows get a value
    # without a rewrite. Every pre-existing row is, by definition, from the old
    # engine — which only ever produced quantified 'affected'/'epicenter' nodes.
    op.add_column(
        "spatial_nodes",
        sa.Column("node_type", sa.String(), nullable=False, server_default="affected"),
    )
    op.add_column(
        "spatial_nodes",
        sa.Column(
            "has_unquantified_direct_edge",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("spatial_nodes", sa.Column("node_id", sa.String(), nullable=True))
    op.add_column("spatial_nodes", sa.Column("country", sa.String(), nullable=True))
    op.add_column("spatial_nodes", sa.Column("order_level", sa.Integer(), nullable=True))
    op.add_column("spatial_nodes", sa.Column("why", sa.Text(), nullable=True))
    op.add_column("spatial_nodes", sa.Column("confidence", sa.Float(), nullable=True))

    # Backfill node_type from the existing is_epicenter flag so the two agree
    # from the moment this lands. (server_default already made every row
    # 'affected'; this promotes the real epicenters.)
    op.execute(
        "UPDATE spatial_nodes SET node_type = 'epicenter' WHERE is_epicenter IS TRUE"
    )

    # ── spatial_edges ────────────────────────────────────────────────────────
    op.alter_column(
        "spatial_edges",
        "edge_intensity",
        existing_type=sa.Float(),
        nullable=True,
        existing_nullable=False,
    )
    op.add_column(
        "spatial_edges",
        sa.Column(
            "unquantified", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("spatial_edges", sa.Column("source_node_id", sa.String(), nullable=True))
    op.add_column("spatial_edges", sa.Column("target_node_id", sa.String(), nullable=True))


def downgrade() -> None:
    # ── spatial_edges ────────────────────────────────────────────────────────
    op.drop_column("spatial_edges", "target_node_id")
    op.drop_column("spatial_edges", "source_node_id")
    op.drop_column("spatial_edges", "unquantified")
    # Re-imposing NOT NULL would FAIL on any row the new producer wrote as null.
    # Collapse those to 0.0 first. This is LOSSY BY NECESSITY: "unmeasured"
    # becomes "zero". That information cannot be preserved in the old schema —
    # which is precisely why this migration exists.
    op.execute("UPDATE spatial_edges SET edge_intensity = 0.0 WHERE edge_intensity IS NULL")
    op.alter_column(
        "spatial_edges",
        "edge_intensity",
        existing_type=sa.Float(),
        nullable=False,
        existing_nullable=True,
    )

    # ── spatial_nodes ────────────────────────────────────────────────────────
    op.drop_column("spatial_nodes", "confidence")
    op.drop_column("spatial_nodes", "why")
    op.drop_column("spatial_nodes", "order_level")
    op.drop_column("spatial_nodes", "country")
    op.drop_column("spatial_nodes", "node_id")
    op.drop_column("spatial_nodes", "has_unquantified_direct_edge")
    op.drop_column("spatial_nodes", "node_type")
    # Same lossy collapse as above.
    op.execute("UPDATE spatial_nodes SET impact_score = 0.0 WHERE impact_score IS NULL")
    op.alter_column(
        "spatial_nodes",
        "impact_score",
        existing_type=sa.Float(),
        nullable=False,
        existing_nullable=True,
    )
