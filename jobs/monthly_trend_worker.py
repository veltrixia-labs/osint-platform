"""
Monthly Trend Flow worker.

Builds and persists one calendar month's flow snapshot into
``monthly_trend_reports``. Idempotent: a month that already has a row is skipped
unless ``force=True``.

Scheduling: ``main_scheduler`` fires this daily but it only runs on day-of-month
== 1, snapshotting the *just-completed* previous month (mirrors the existing
monthly_reports_wrapper pattern).

Run manually / backfill:

    python -m jobs.monthly_trend_worker                 # previous calendar month
    python -m jobs.monthly_trend_worker --year 2026 --month 4
    python -m jobs.monthly_trend_worker --year 2026 --month 4 --force
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import MonthlyTrendReport
from analysis.monthly_trend_builder import build_monthly_trend_snapshot, month_bounds

logger = logging.getLogger(__name__)


def _previous_month(now: Optional[datetime] = None) -> tuple[int, int]:
    """(year, month) of the calendar month before ``now`` (UTC)."""
    now = now or datetime.now(timezone.utc)
    if now.month == 1:
        return now.year - 1, 12
    return now.year, now.month - 1


async def run_monthly_trend_worker(
    session: Optional[AsyncSession] = None,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Build + upsert the snapshot for (year, month). Defaults to previous month."""
    if year is None or month is None:
        year, month = _previous_month()

    owns_session = session is None
    if owns_session:
        session = AsyncSessionLocal()

    try:
        assert session is not None
        existing = (
            await session.execute(
                select(MonthlyTrendReport).where(
                    MonthlyTrendReport.period_year == year,
                    MonthlyTrendReport.period_month == month,
                )
            )
        ).scalar_one_or_none()

        if existing is not None and not force:
            logger.info(
                "Monthly trend for %04d-%02d already exists (id=%s); skipping (use force=True to rebuild).",
                year, month, existing.id,
            )
            return {"status": "skipped_existing", "year": year, "month": month}

        start, end, label = month_bounds(year, month)
        snapshot = await build_monthly_trend_snapshot(session, year, month)
        summary = snapshot["summary"]

        if existing is not None:
            existing.period_start = start
            existing.period_end = end
            existing.label = label
            existing.generated_at = datetime.now(timezone.utc)
            existing.schema_version = snapshot["schema_version"]
            existing.nodes_payload = snapshot["nodes"]
            existing.edges_payload = snapshot["edges"]
            existing.summary_json = summary
            existing.alerts_total = int(summary.get("alerts_total", 0))
            existing.alerts_spiked = int(summary.get("alerts_spiked", 0))
            action = "rebuilt"
        else:
            session.add(
                MonthlyTrendReport(
                    id=uuid.uuid4(),
                    period_year=year,
                    period_month=month,
                    period_start=start,
                    period_end=end,
                    label=label,
                    generated_at=datetime.now(timezone.utc),
                    schema_version=snapshot["schema_version"],
                    nodes_payload=snapshot["nodes"],
                    edges_payload=snapshot["edges"],
                    summary_json=summary,
                    alerts_total=int(summary.get("alerts_total", 0)),
                    alerts_spiked=int(summary.get("alerts_spiked", 0)),
                )
            )
            action = "created"

        await session.commit()
        logger.info(
            "Monthly trend %s for %s: alerts=%s spiked=%s nodes=%s edges=%s",
            action, label, summary.get("alerts_total"), summary.get("alerts_spiked"),
            summary.get("node_count"), summary.get("edge_count"),
        )
        return {
            "status": action,
            "year": year,
            "month": month,
            "label": label,
            "summary": summary,
        }
    except Exception:
        if session is not None:
            await session.rollback()
        logger.exception("Monthly trend worker failed for %04d-%02d", year, month)
        raise
    finally:
        if owns_session and session is not None:
            await session.close()


async def _main() -> None:
    p = argparse.ArgumentParser(description="Build a Monthly Trend Flow snapshot")
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--month", type=int, default=None)
    p.add_argument("--force", action="store_true", help="Rebuild even if the month already exists")
    args = p.parse_args()
    result = await run_monthly_trend_worker(year=args.year, month=args.month, force=args.force)
    print(result)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
