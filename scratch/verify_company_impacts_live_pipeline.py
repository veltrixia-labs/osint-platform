"""
Live pipeline: RSS ingest → normalize → classify → signal → trend → alert_manager
(free_alert + company_impacts are persisted inside alert_manager when alerts fire).

Then scan recent AlertLog rows for location_entity_id / company_impacts / Hormuz–Red Sea text.
If no Hormuz-related alert exists, inserts a dummy AlertLog and runs persist_free_alert_feed_item.

Usage (repo root):
  .venv\\Scripts\\python.exe scratch/verify_company_impacts_live_pipeline.py
  .venv\\Scripts\\python.exe scratch/verify_company_impacts_live_pipeline.py --skip-ingest
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import AlertLog

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("verify_company_impacts")


GEO_KEYWORDS = re.compile(
    r"hormuz|strait\s+of\s+hormuz|red\s+sea|bab\s+el|ホルムズ|紅海",
    re.I,
)


async def run_full_pipeline(skip_ingest: bool) -> None:
    from jobs.ingest_job import run_ingest
    from processor.normalize import run_normalize
    from processor.classify import run_classify
    from jobs.signal_job import run_signal
    from jobs.trend_analyze_job import run_trend_analysis
    from jobs.alert_manager import run_alert_manager

    async with AsyncSessionLocal() as db:
        if not skip_ingest:
            logger.info("=== 1/6 ingest_job (RSS → RawItem) ===")
            await run_ingest(db)
        else:
            logger.info("=== 1/6 ingest skipped ===")

        logger.info("=== 2/6 normalize (RawItem → Item) ===")
        await run_normalize(db)

        logger.info("=== 3/6 classify ===")
        await run_classify(db)

        logger.info("=== 4/6 signal_job ===")
        await run_signal(db)

        logger.info("=== 5/6 trend_analyze_job ===")
        await run_trend_analysis(db)

        logger.info("=== 6/6 alert_manager (TrendSignal → AlertLog + free_alert persist) ===")
        await run_alert_manager(db)


def _alert_text_blob(meta: dict, alert: AlertLog) -> str:
    parts = [alert.target_label or "", str(meta.get("description") or "")]
    fa = meta.get("free_alert")
    if isinstance(fa, dict):
        parts.extend([str(fa.get("title") or ""), str(fa.get("target_label") or "")])
    return " ".join(parts)


async def scan_recent_alerts(limit: int = 40) -> list[AlertLog]:
    async with AsyncSessionLocal() as db:
        stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(limit)
        return list((await db.execute(stmt)).scalars().all())


async def refresh_free_alerts_missing_company_impacts(limit: int = 30) -> int:
    """Re-persist free_alert so API gains company_impacts for older rows."""
    from jobs.free_alert_feed_generator import persist_free_alert_feed_item

    n = 0
    async with AsyncSessionLocal() as db:
        stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(limit)
        rows = list((await db.execute(stmt)).scalars().all())
        for alert in rows:
            meta = alert.metadata_json if isinstance(alert.metadata_json, dict) else {}
            fa = meta.get("free_alert")
            if not isinstance(fa, dict):
                continue
            if fa.get("company_impacts"):
                continue
            try:
                await persist_free_alert_feed_item(db, alert)
                n += 1
            except Exception as e:
                logger.warning("persist failed id=%s: %s", alert.id, e)
    return n


async def insert_dummy_hormuz_alert() -> AlertLog:
    from jobs.free_alert_feed_generator import persist_free_alert_feed_item

    async with AsyncSessionLocal() as db:
        alert = AlertLog(
            target_label="TEST Hormuz Strait shipping lane watch",
            topic="energy_resource_risk",
            trigger_type="pattern_risk",
            severity="elevated",
            intensity=8.5,
            intelligence_score=0.55,
            fidelity_score=0.35,
            is_high_fidelity=False,
            status="confirmed",
            is_system_wide=True,
            supporting_events_count=2,
            location_lat=26.56,
            location_lng=56.25,
            metadata_json={
                "description": (
                    "Dummy article for pipeline test: Strait of Hormuz crude tanker "
                    "traffic and regional energy logistics risk."
                ),
                "evidence_list": [
                    {"title": "Strait of Hormuz maritime security", "headline": "Hormuz Strait"},
                ],
                "related_item_ids": [],
                "domain_count": 2,
                "spike_delta": 0.0,
                "scoring_breakdown": {},
            },
        )
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
        logger.info("Inserted dummy AlertLog id=%s", alert.id)
        await persist_free_alert_feed_item(db, alert)
        await db.refresh(alert)
        return alert


def log_scan_results(rows: list[AlertLog]) -> bool:
    """Returns True if any row matches GEO_KEYWORDS and has company_impacts."""
    found_geo_with_impacts = False
    logger.info("--- Scan: last %s AlertLog rows ---", len(rows))
    for alert in rows:
        meta = alert.metadata_json if isinstance(alert.metadata_json, dict) else {}
        loc_id = meta.get("location_entity_id")
        loc_res = meta.get("location_resolution") or {}
        fa = meta.get("free_alert")
        impacts = fa.get("company_impacts") if isinstance(fa, dict) else None
        n_imp = len(impacts) if isinstance(impacts, list) else 0
        blob = _alert_text_blob(meta, alert)
        geo_hit = bool(GEO_KEYWORDS.search(blob))
        line = (
            f"id={alert.id} topic={alert.topic!r} "
            f"location_entity_id={loc_id!r} "
            f"resolution_name={loc_res.get('display_name')!r} "
            f"company_impacts_count={n_imp} "
            f"geo_keyword_hit={geo_hit}"
        )
        if geo_hit or loc_id in ("hormuz-strait", "red-sea"):
            logger.info(">> %s", line)
            if n_imp > 0:
                found_geo_with_impacts = True
                for i, row in enumerate((impacts or [])[:5]):
                    logger.info(
                        "   impact[%s]: %s | %s",
                        i,
                        (row or {}).get("company_name"),
                        (row or {}).get("match_basis"),
                    )
        else:
            logger.debug(line)
    return found_geo_with_impacts


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-ingest", action="store_true", help="Skip RSS fetch (faster retest)")
    args = parser.parse_args()

    await run_full_pipeline(skip_ingest=args.skip_ingest)

    refreshed = await refresh_free_alerts_missing_company_impacts(limit=40)
    logger.info("Refreshed free_alert (added company_impacts) for %s rows", refreshed)

    rows = await scan_recent_alerts(limit=50)
    ok = log_scan_results(rows)

    if not ok:
        logger.warning(
            "No recent alert matched Hormuz/Red Sea keywords with non-empty company_impacts; "
            "inserting dummy Hormuz alert."
        )
        dummy = await insert_dummy_hormuz_alert()
        rows2 = await scan_recent_alerts(limit=5)
        log_scan_results(rows2)
        meta = dummy.metadata_json if isinstance(dummy.metadata_json, dict) else {}
        fa = meta.get("free_alert") if isinstance(meta.get("free_alert"), dict) else {}
        logger.info(
            "Dummy summary: location_entity_id=%r company_impacts=%s",
            meta.get("location_entity_id"),
            len(fa.get("company_impacts") or []),
        )
    else:
        logger.info("Pipeline scan: Hormuz/Red Sea–related row(s) with company_impacts present.")


if __name__ == "__main__":
    asyncio.run(main())
