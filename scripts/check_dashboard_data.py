"""
Verify production DB has data for the dashboard (AlertLog, free_alert payloads, RawItem).

Usage (repo root, DATABASE_URL or .env configured):
  py -3 scripts/check_dashboard_data.py
  py -3 scripts/check_dashboard_data.py --ingest
  py -3 scripts/check_dashboard_data.py --backfill-free --limit 50

--ingest        Run jobs.ingest_job.run_ingest (RSS -> raw_items).
--backfill-free Run persist_free_alert_feed_item on recent AlertLog rows (Context Briefs).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import cast, String, func, select, or_

from db.database import AsyncSessionLocal
from db.models import AlertLog, RawItem

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("check_dashboard_data")


async def counts(db) -> dict:
    n_alerts = (await db.execute(select(func.count()).select_from(AlertLog))).scalar_one()
    n_raw = (await db.execute(select(func.count()).select_from(RawItem))).scalar_one()
    key = AlertLog.metadata_json["free_alert"]
    text_blob = cast(AlertLog.metadata_json, String)
    stmt_fa = (
        select(func.count())
        .select_from(AlertLog)
        .where(or_(key.is_not(None), text_blob.contains('"free_alert"')))
    )
    n_free = (await db.execute(stmt_fa)).scalar_one()
    return {"alert_logs": int(n_alerts or 0), "raw_items": int(n_raw or 0), "alert_logs_with_free_alert": int(n_free or 0)}


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ingest", action="store_true", help="Run RSS ingest (raw_items)")
    p.add_argument("--backfill-free", action="store_true", help="Persist free_alert onto recent AlertLog rows")
    p.add_argument("--limit", type=int, default=50, help="Max rows for --backfill-free")
    args = p.parse_args()

    async with AsyncSessionLocal() as db:
        c = await counts(db)
        logger.info("DB snapshot: %s", c)
        na, nf = c["alert_logs"], c["alert_logs_with_free_alert"]
        if na:
            logger.info(
                "free_alert coverage: %s / %s (%.1f%%)",
                nf,
                na,
                100.0 * nf / na,
            )

        if c["alert_logs"] == 0:
            logger.warning(
                "No AlertLog rows. Ingest alone only fills raw_items; run the processing "
                "scheduler / alert pipeline to create alerts, then --backfill-free."
            )
        if c["alert_logs_with_free_alert"] == 0 and c["alert_logs"] > 0:
            logger.warning(
                "AlertLog rows exist but none have metadata_json.free_alert (Context Briefs API returns []). "
                "Run: py -3 scripts/check_dashboard_data.py --backfill-free"
            )

        if args.ingest:
            from jobs.ingest_job import run_ingest

            logger.info("Running ingest_job...")
            await run_ingest(db)
            c2 = await counts(db)
            logger.info("After ingest: %s", c2)

        if args.backfill_free:
            from jobs.free_alert_feed_generator import persist_free_alert_feed_item

            stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(args.limit)
            rows = list((await db.execute(stmt)).scalars().all())
            ok = 0
            for alert in rows:
                try:
                    await persist_free_alert_feed_item(db, alert)
                    ok += 1
                except Exception as e:
                    logger.error("persist failed %s: %s", alert.id, e)
            logger.info("backfill-free done: processed=%s ok=%s", len(rows), ok)
            c3 = await counts(db)
            logger.info("After backfill: %s", c3)


if __name__ == "__main__":
    asyncio.run(main())
