"""
Test script for BEA query layer.

Exercises all query functions against the local DB.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import AsyncSessionLocal
from data_sources.bea_query import (
    get_total_gdp_by_year,
    get_top_industries_by_year,
    get_industry_timeseries,
    get_sector_share,
)


async def main():
    async with AsyncSessionLocal() as session:

        # ── 1. Total GDP for 2022 ────────────────────────────────────
        print("=" * 60)
        print("1. Total GDP for 2022")
        print("=" * 60)
        gdp = await get_total_gdp_by_year(session, "2022")
        if gdp:
            print(f"   {gdp['industry_description']}: ${gdp['data_value']:,.1f}B")
            print(f"   Note: {gdp['note_text']}")
        else:
            print("   No GDP data found for 2022.")

        # ── 2. Top 10 Industries for 2022 ────────────────────────────
        print()
        print("=" * 60)
        print("2. Top 10 Industries by Value Added (2022)")
        print("=" * 60)
        top = await get_top_industries_by_year(session, "2022", top_n=10)
        for row in top:
            print(f"   #{row['rank']:>2}  {row['industry']:>8s}  "
                  f"${row['data_value']:>10,.1f}B  {row['industry_description']}")

        # ── 3. Manufacturing (31G) check ─────────────────────────────
        print()
        print("=" * 60)
        print("3. Manufacturing (31G) Timeseries")
        print("=" * 60)
        ts = await get_industry_timeseries(session, "31G")
        if ts:
            for point in ts:
                print(f"   {point['year']}: ${point['data_value']:,.1f}B"
                      f"  ({point['industry_description']})")
        else:
            print("   No timeseries data for 31G (only 2022 loaded).")
            # Fallback: show the single-year value
            top_all = await get_top_industries_by_year(
                session, "2022", top_n=100, exclude_aggregates=False
            )
            mfg = [r for r in top_all if r["industry"] == "31G"]
            if mfg:
                print(f"   2022 value: ${mfg[0]['data_value']:,.1f}B")

        # ── 4. Sector Share — Top 5 ──────────────────────────────────
        print()
        print("=" * 60)
        print("4. GDP Sector Share - Top 5 (2022)")
        print("=" * 60)
        shares = await get_sector_share(session, "2022")
        for row in shares[:5]:
            bar = "#" * int(row["share_pct"])
            print(f"   {row['industry']:>8s}  {row['share_pct']:>5.2f}%  "
                  f"{bar}  {row['industry_description']}")

        # ── Summary ──────────────────────────────────────────────────
        print()
        print("=" * 60)
        print("Summary")
        print("=" * 60)
        if shares:
            total_share = sum(r["share_pct"] for r in shares)
            print(f"   Non-aggregate sectors: {len(shares)}")
            print(f"   Sum of shares: {total_share:.2f}%")
            print(f"   (Expected >100% due to sub-industry overlap in BEA data)")


if __name__ == "__main__":
    asyncio.run(main())
