"""
Retention policy for Pro Structural Briefs (Pro Insight hub).

Deletes pro_structural report rows older than the configured window (default 90 days).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models import Report

logger = logging.getLogger(__name__)


def _pro_structural_filter():
    return (
        Report.plan_required == "pro",
        Report.is_premium == True,  # noqa: E712
        or_(
            Report.report_type == "pro_structural",
            Report.title.ilike("Structural Impact Brief%"),
        ),
    )


async def count_pro_structural_reports_older_than(
    db: AsyncSession,
    threshold: datetime,
) -> int:
    stmt = select(func.count(Report.id)).where(
        *_pro_structural_filter(),
        Report.created_at < threshold,
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def run_pro_structural_retention_cleanup(
    db: AsyncSession,
    *,
    dry_run: bool | None = None,
    retention_days: int | None = None,
) -> dict:
    """
    Permanently delete Pro Structural Brief rows older than retention_days (default 90).
    """
    if dry_run is None:
        dry_run = settings.retention_dry_run
    days = retention_days if retention_days is not None else settings.pro_structural_retention_days
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=days)
    mode = "[DRY RUN] " if dry_run else ""

    pending = await count_pro_structural_reports_older_than(db, threshold)
    deleted = 0

    if pending and not dry_run:
        stmt = delete(Report).where(*_pro_structural_filter(), Report.created_at < threshold)
        result = await db.execute(stmt)
        deleted = int(result.rowcount or 0)
        await db.commit()

    logger.info(
        "%sPro structural retention: %s rows older than %s days (pending=%s, deleted=%s)",
        mode,
        pending,
        days,
        pending,
        deleted,
    )
    return {
        "retention_days": days,
        "threshold": threshold.isoformat(),
        "pending_delete": pending,
        "deleted": deleted if not dry_run else 0,
        "dry_run": dry_run,
    }
