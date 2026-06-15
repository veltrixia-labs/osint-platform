"""
Backfill Monthly Trend Flow snapshots for the last N months.

Idempotent: months that already have a row are skipped unless --force.

Usage (repo root, DATABASE_URL or .env):
  py -3 scripts/backfill_monthly_trends.py                 # last 6 months
  py -3 scripts/backfill_monthly_trends.py --months 12
  py -3 scripts/backfill_monthly_trends.py --months 3 --force
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.monthly_trend_worker import run_monthly_trend_worker

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill_monthly_trends")


def _months_back(n: int) -> list[tuple[int, int]]:
    """The N most-recent *completed* months (newest first), excluding the current month."""
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    out: list[tuple[int, int]] = []
    for _ in range(n):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        out.append((year, month))
    return out


async def main() -> None:
    p = argparse.ArgumentParser(description="Backfill monthly trend snapshots")
    p.add_argument("--months", type=int, default=6, help="How many prior months (default 6)")
    p.add_argument("--force", action="store_true", help="Rebuild even if a month already exists")
    args = p.parse_args()

    targets = _months_back(args.months)
    logger.info("Backfilling %s month(s): %s", len(targets), targets)

    async with AsyncSessionLocal() as session:
        for year, month in targets:
            try:
                result = await run_monthly_trend_worker(
                    session, year=year, month=month, force=args.force
                )
                logger.info("%04d-%02d: %s", year, month, result.get("status"))
            except Exception as e:
                logger.error("%04d-%02d failed: %s", year, month, e)


if __name__ == "__main__":
    asyncio.run(main())
