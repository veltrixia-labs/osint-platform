"""
Verify production DB has data for the dashboard (AlertLog, RawItem).

Usage (repo root, DATABASE_URL or .env configured):
  py -3 scripts/check_dashboard_data.py
  py -3 scripts/check_dashboard_data.py --ingest

--ingest        Run jobs.ingest_job.run_ingest (RSS -> raw_items).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import func, select

from db.database import AsyncSessionLocal
from db.models import AlertLog, RawItem

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("check_dashboard_data")


async def counts(db) -> dict:
    n_alerts = (await db.execute(select(func.count()).select_from(AlertLog))).scalar_one()
    n_raw = (await db.execute(select(func.count()).select_from(RawItem))).scalar_one()
    return {"alert_logs": int(n_alerts or 0), "raw_items": int(n_raw or 0)}


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ingest", action="store_true", help="Run RSS ingest (raw_items)")
    args = p.parse_args()

    async with AsyncSessionLocal() as db:
        c = await counts(db)
        logger.info("DB snapshot: %s", c)

        if c["alert_logs"] == 0:
            logger.warning(
                "No AlertLog rows. Ingest alone only fills raw_items; run the processing "
                "scheduler / alert pipeline to create alerts."
            )

        if args.ingest:
            from jobs.ingest_job import run_ingest

            logger.info("Running ingest_job...")
            await run_ingest(db)
            c2 = await counts(db)
            logger.info("After ingest: %s", c2)


if __name__ == "__main__":
    asyncio.run(main())
