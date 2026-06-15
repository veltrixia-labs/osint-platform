"""
One-shot seed script: pull the last 52 weeks of CFTC COT positioning for
every market in `cftc_series_catalog.get_tracked_cot_markets()` and write
the rows into `cot_reports`.

Uses the public Socrata endpoint — no API key, no env vars required.

Run:
    .venv\\Scripts\\python.exe scratch\\seed_cftc_data.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select, func
from db.database import AsyncSessionLocal
from db.models import COTReport
from jobs.cftc_sync_job import run_cftc_sync


async def _print_summary() -> None:
    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(func.count(COTReport.id)))).scalar() or 0
        per_market = (
            await session.execute(
                select(COTReport.market_and_exchange, func.count(COTReport.id))
                .group_by(COTReport.market_and_exchange)
                .order_by(COTReport.market_and_exchange)
            )
        ).all()
        latest = (
            await session.execute(
                select(func.max(COTReport.report_date))
            )
        ).scalar()
    print(f"\n[summary] cot_reports total rows: {total}")
    print(f"[summary] latest report_date     : {latest}")
    print("[summary] per market:")
    for market, n in per_market:
        print(f"  {n:>4} rows — {market}")


async def main() -> int:
    print("Seeding CFTC Commitments of Traders (last 52 weeks × tracked markets)…")
    summary = await run_cftc_sync(weeks=52)
    print("\nSync summary:")
    for key in ("markets", "rows_inserted", "rows_updated", "rows_skipped"):
        print(f"  {key:18s}: {summary.get(key)}")
    print("Per market:")
    for row in summary.get("per_market", []):
        if "error" in row:
            print(f"  {row['market']:38s} ERROR: {row['error'][:80]}")
        else:
            print(f"  {row['market']:38s} fetched={row['rows']:3d}  ins={row['inserted']:3d}  upd={row['updated']:3d}  skip={row['skipped']}")
    await _print_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
