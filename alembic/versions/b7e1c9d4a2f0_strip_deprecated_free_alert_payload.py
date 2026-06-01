"""Strip deprecated free_alert (Context Briefs) payload from alert_logs.metadata_json

Revision ID: b7e1c9d4a2f0
Revises: 8d599ede075c
Create Date: 2026-05-30 00:00:00.000000

Context Briefs (a.k.a. the "free_alert" / Free Alert Feed) has been fully
deprecated and removed. The feature never had a dedicated table or column — its
data lived as a nested JSON key ``metadata_json['free_alert']`` inside the
shared ``alert_logs`` row (co-owned by the live Alert Stream). This is therefore
a DATA migration only (no DDL / column drop): it removes the now-orphaned
``free_alert`` key from every alert_logs row so no stale payload remains.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7e1c9d4a2f0'
down_revision: Union[str, Sequence[str], None] = '8d599ede075c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove the deprecated metadata_json['free_alert'] key from all alert_logs."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # JSONB key-removal: `- 'free_alert'` strips the key; `? 'free_alert'`
        # restricts the UPDATE to rows that actually carry it.
        op.execute(
            "UPDATE alert_logs "
            "SET metadata_json = metadata_json - 'free_alert' "
            "WHERE metadata_json ? 'free_alert'"
        )
    # Non-postgres backends (e.g. SQLite in tests) store metadata_json as text
    # and have no live free_alert data — nothing to strip.


def downgrade() -> None:
    """Irreversible: the deprecated free_alert payload is not reconstructable."""
    pass
