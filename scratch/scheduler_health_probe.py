"""Read-only scheduler/ingestion health probe (queries prod DB via .env).

No writes. Reports: scheduler_heartbeat freshness, raw-signal + item + alert
inflow over recent windows, and the classification mix of the latest items so we
can confirm the strict boundary rules are holding (no fresh AI ghosts)."""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, func
from db.database import AsyncSessionLocal
from db.models import RawItem, Item, AlertLog, SystemMetric


async def _count(s, model, col, since) -> int:
    return (await s.execute(select(func.count()).select_from(model).where(col >= since))).scalar() or 0


async def main() -> None:
    now = datetime.now(timezone.utc)
    m10, h2 = now - timedelta(minutes=10), now - timedelta(hours=2)
    print(f"\n=== Scheduler/ingestion health probe @ {now.isoformat()} (READ-ONLY) ===")

    async with AsyncSessionLocal() as s:
        hb = (await s.execute(
            select(SystemMetric).where(SystemMetric.metric_key == "scheduler_heartbeat")
        )).scalar_one_or_none()
        if hb and hb.metric_value:
            try:
                last = datetime.fromisoformat(hb.metric_value)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age = (now - last).total_seconds()
                state = "ACTIVE" if age < 180 else f"STALE ({int(age)}s old)"
                print(f"scheduler_heartbeat: {hb.metric_value}  -> {state}")
            except Exception as e:
                print(f"scheduler_heartbeat: unpar+seable ({hb.metric_value}) {e}")
        else:
            print("scheduler_heartbeat: <none recorded>")

        print("\n-- inflow --")
        print(f"raw_items  last 10m: {await _count(s, RawItem, RawItem.fetched_at, m10):5d}   last 2h: {await _count(s, RawItem, RawItem.fetched_at, h2)}")
        print(f"items      last 10m: {await _count(s, Item, Item.created_at, m10):5d}   last 2h: {await _count(s, Item, Item.created_at, h2)}")
        print(f"alert_logs last 10m: {await _count(s, AlertLog, AlertLog.triggered_at, m10):5d}   last 2h: {await _count(s, AlertLog, AlertLog.triggered_at, h2)}")

        print("\n-- classification mix of items created in last 2h (strict-rules check) --")
        rows = (await s.execute(select(Item.category).where(Item.created_at >= h2))).scalars().all()
        mix = Counter(c or "<null>" for c in rows)
        if not mix:
            print("  (no items created in the last 2h)")
        for cat, n in mix.most_common():
            print(f"  {n:5d}  {cat}")


if __name__ == "__main__":
    asyncio.run(main())
