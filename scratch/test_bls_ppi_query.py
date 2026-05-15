import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import AsyncSessionLocal
from data_sources.bls_ppi_query import (
    get_ppi_latest,
    get_ppi_timeseries,
    get_ppi_yoy_change,
    get_ppi_mom_change,
    get_ppi_period_change,
    get_all_latest_ppi,
    get_ppi_pressure_summary
)

async def test_ppi_queries():
    async with AsyncSessionLocal() as session:
        print("="*60)
        print("PPI INDIVIDUAL QUERIES (WPUFD4: Final Demand)")
        print("="*60)
        
        # 1. Latest
        latest = await get_ppi_latest(session, "WPUFD4")
        if latest:
            print(f"Latest (2024-12): {latest['value']} ({latest['series_name']})")
        
        # 2. Timeseries
        ts = await get_ppi_timeseries(session, "WPUFD4", "2018-01", "2024-12")
        print(f"Timeseries points (2018-01 to 2024-12): {len(ts)}")

        # 3. YoY
        yoy = await get_ppi_yoy_change(session, "WPUFD4", "2024-12")
        print(f"YoY Change (2024-12 vs 2023-12): {yoy['change_percent']}%")

        # 4. MoM
        mom = await get_ppi_mom_change(session, "WPUFD4", "2024-12")
        print(f"MoM Change (2024-12 vs 2024-11): {mom['change_percent']}%")

        # 5. Cumulative
        cum = await get_ppi_period_change(session, "WPUFD4", "2018-01", "2024-12")
        print(f"Cumulative Change (2018-01 to 2024-12): {cum['change_percent']}%")

        print("\n" + "="*60)
        print("ALL LATEST PPI SERIES")
        print("="*60)
        all_latest = await get_all_latest_ppi(session)
        for row in all_latest:
            print(f"  {row['series_id']:<12}: {row['value']:>8.3f} | {row['series_name']}")

        print("\n" + "="*60)
        print("PPI PRICE PRESSURE SUMMARY (As of 2024-12)")
        print("="*60)
        print(f"  {'Series':<12} | {'Value':>8} | {'YoY':>6} | {'MoM':>6} | {'Cum %':>6}")
        print("-" * 60)
        summary = await get_ppi_pressure_summary(session, "2024-12")
        for s in summary:
            print(f"  {s['series_id']:<12} | {s['value']:>8.2f} | {s['yoy_pct']:>5.1f}% | {s['mom_pct']:>5.1f}% | {s['cum_pct']:>5.1f}%")

if __name__ == "__main__":
    asyncio.run(test_ppi_queries())
