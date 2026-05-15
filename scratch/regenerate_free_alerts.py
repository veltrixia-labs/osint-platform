"""
Re-build metadata_json.free_alert for recent AlertLog rows (Context Briefs).

Usage (repo root):
  .venv\\Scripts\\python.exe scratch/regenerate_free_alerts.py
  .venv\\Scripts\\python.exe scratch/regenerate_free_alerts.py --limit 50
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import AlertLog
from jobs.free_alert_feed_generator import persist_free_alert_feed_item

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("regenerate_free_alerts")


async def main(limit: int) -> None:
    ok = 0
    failed = 0
    async with AsyncSessionLocal() as db:
        stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(limit)
        rows = list((await db.execute(stmt)).scalars().all())
        logger.info("Regenerating free_alert for %s AlertLog row(s)...", len(rows))
        for alert in rows:
            try:
                await persist_free_alert_feed_item(db, alert)
                ok += 1
                logger.info("OK %s | %s", alert.id, (alert.target_label or "")[:60])
            except Exception as e:
                failed += 1
                logger.error("FAIL %s: %s", alert.id, e)
    logger.info("Done. success=%s failed=%s", ok, failed)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=200, help="Max alerts to process (default 200)")
    args = p.parse_args()
    asyncio.run(main(args.limit))
