"""
Weekly CFTC Commitments of Traders sync.

For each market in `cftc_series_catalog.get_tracked_cot_markets()` we fetch
the latest N weeks of disaggregated futures positioning via the Socrata public
API (no key required), then upsert into the `cot_reports` table.

Designed to be safe to re-run: the `(market_and_exchange, report_date)`
unique constraint short-circuits duplicate inserts.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import COTReport
from data_sources.cftc_client import CFTCClient
from data_sources.cftc_series_catalog import get_tracked_cot_markets

logger = logging.getLogger(__name__)


def _parse_report_date(value: Any) -> datetime | None:
    if not value:
        return None
    s = str(value)
    for fmt, size in (("%Y-%m-%d", 10), ("%Y-%m-%dT%H:%M:%S", 19)):
        try:
            return datetime.strptime(s[:size], fmt)
        except ValueError:
            continue
    return None


async def upsert_cot_rows(
    session: AsyncSession,
    rows: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Upsert COT rows. Returns ``{inserted, updated, skipped}``.
    Uses a per-row lookup keyed on (market, report_date) — the table only
    holds ~52 rows × ~6 markets so this is cheap and dialect-portable.
    """
    inserted = 0
    updated = 0
    skipped = 0
    for row in rows:
        report_date = _parse_report_date(row.get("report_date"))
        market = row.get("market_and_exchange")
        if not report_date or not market:
            skipped += 1
            continue

        stmt = (
            select(COTReport)
            .where(
                COTReport.market_and_exchange == market,
                COTReport.report_date == report_date,
            )
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing is None:
            session.add(COTReport(
                market_and_exchange=market,
                report_date=report_date,
                yyyy_report_week_ww=row.get("yyyy_report_week_ww"),
                open_interest_all=row.get("open_interest_all"),
                noncomm_long=row.get("noncomm_long"),
                noncomm_short=row.get("noncomm_short"),
                noncomm_spread=row.get("noncomm_spread"),
                comm_long=row.get("comm_long"),
                comm_short=row.get("comm_short"),
                nonrept_long=row.get("nonrept_long"),
                nonrept_short=row.get("nonrept_short"),
                raw_json=row.get("raw_json"),
            ))
            inserted += 1
        else:
            existing.open_interest_all = row.get("open_interest_all")
            existing.noncomm_long = row.get("noncomm_long")
            existing.noncomm_short = row.get("noncomm_short")
            existing.noncomm_spread = row.get("noncomm_spread")
            existing.comm_long = row.get("comm_long")
            existing.comm_short = row.get("comm_short")
            existing.nonrept_long = row.get("nonrept_long")
            existing.nonrept_short = row.get("nonrept_short")
            existing.raw_json = row.get("raw_json")
            updated += 1

    await session.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


async def run_cftc_sync(
    *,
    weeks: int = 52,
) -> Dict[str, Any]:
    """
    Sync every tracked CFTC market for the last `weeks` reporting periods.
    Safe to run weekly via the scheduler or ad-hoc from a seed script.
    """
    client = CFTCClient()
    markets = get_tracked_cot_markets()
    if not markets:
        logger.warning("CFTC sync: no tracked markets configured.")
        return {"markets": 0, "rows_inserted": 0, "rows_updated": 0}

    total_inserted = 0
    total_updated = 0
    total_skipped = 0
    per_market: List[Dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        for market in markets:
            label = market.get("label") or market["market_and_exchange"]
            try:
                rows = client.fetch_market(market["market_and_exchange"], limit=weeks)
            except Exception as exc:
                logger.warning("CFTC fetch failed for %s: %s", label, exc)
                per_market.append({"market": label, "error": str(exc)})
                continue

            stats = await upsert_cot_rows(session, rows)
            per_market.append({"market": label, "rows": len(rows), **stats})
            total_inserted += stats["inserted"]
            total_updated += stats["updated"]
            total_skipped += stats["skipped"]
            logger.info(
                "CFTC sync %s: fetched=%d ins=%d upd=%d skip=%d",
                label, len(rows), stats["inserted"], stats["updated"], stats["skipped"],
            )

    return {
        "markets": len(markets),
        "rows_inserted": total_inserted,
        "rows_updated": total_updated,
        "rows_skipped": total_skipped,
        "per_market": per_market,
        "completed_at": datetime.utcnow().isoformat() + "Z",
    }
