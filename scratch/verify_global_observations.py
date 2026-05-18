"""Log ExternalObservation counts and samples for global sync sources."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import desc, func, select

from db.database import AsyncSessionLocal
from db.models import ExternalObservation

FOCUS_SOURCES = ("estat", "eia", "ecb", "opec", "asean", "bcb")
ALL_SOURCES = (
    "fred",
    "bls",
    "worldbank",
    "comtrade",
    "bea",
    "census",
    *FOCUS_SOURCES,
)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        print("=" * 72)
        print("ExternalObservation counts by source")
        print("=" * 72)
        for src in ALL_SOURCES:
            cnt = (
                await session.execute(
                    select(func.count())
                    .select_from(ExternalObservation)
                    .where(ExternalObservation.source == src)
                )
            ).scalar() or 0
            flag = " ***" if src in FOCUS_SOURCES and cnt == 0 else ""
            print(f"  {src:12} {cnt:6}{flag}")

        print("\n" + "=" * 72)
        print("Latest observation per focus source (up to 3 series each)")
        print("=" * 72)
        for src in FOCUS_SOURCES:
            subq = (
                select(
                    ExternalObservation.series_id,
                    func.max(ExternalObservation.date).label("max_date"),
                )
                .where(ExternalObservation.source == src)
                .group_by(ExternalObservation.series_id)
                .subquery()
            )
            rows = (
                await session.execute(
                    select(ExternalObservation)
                    .join(
                        subq,
                        (ExternalObservation.series_id == subq.c.series_id)
                        & (ExternalObservation.date == subq.c.max_date)
                        & (ExternalObservation.source == src),
                    )
                    .order_by(desc(ExternalObservation.date))
                    .limit(3)
                )
            ).scalars().all()
            print(f"\n--- {src} ({len(rows)} sample rows) ---")
            if not rows:
                print("  (no data)")
                continue
            for obs in rows:
                print(
                    f"  {obs.series_id} | value={obs.value} | "
                    f"date={obs.date} | period={obs.period_label}"
                )


if __name__ == "__main__":
    asyncio.run(main())
