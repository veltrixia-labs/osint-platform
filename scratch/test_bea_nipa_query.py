import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import AsyncSessionLocal
from data_sources.bea_nipa_query import (
    get_nipa_observation,
    get_gdp_current_dollars_timeseries,
    get_gdp_growth_rate_timeseries,
    get_pce_current_dollars_timeseries,
    get_table_snapshot
)

async def test_nipa_queries():
    async with AsyncSessionLocal() as session:
        print("="*60)
        print("NIPA Individual Queries (2024)")
        print("="*60)
        
        # 1. 2024 GDP current dollars
        gdp_level = await get_nipa_observation(session, "T10105", "1", "2024")
        if gdp_level:
            print(f"GDP (Current Dollars) 2024: ${gdp_level['data_value']:,.1f} ({gdp_level['cl_unit']}, Mult={gdp_level['unit_mult']})")
        
        # 2. 2024 GDP growth rate
        gdp_growth = await get_nipa_observation(session, "T10101", "1", "2024")
        if gdp_growth:
            print(f"GDP Growth Rate 2024: {gdp_growth['data_value']}% ({gdp_growth['cl_unit']})")
            
        # 3. 2024 PCE current dollars
        pce_level = await get_nipa_observation(session, "T20305", "1", "2024")
        if pce_level:
            print(f"PCE (Current Dollars) 2024: ${pce_level['data_value']:,.1f} ({pce_level['cl_unit']})")

        print("\n" + "="*60)
        print("GDP Current Dollars Timeseries (2018-2024)")
        print("="*60)
        ts_gdp = await get_gdp_current_dollars_timeseries(session)
        for row in ts_gdp:
            # Simple conversion to Trillions if scale is Millions (mult=6)
            val_trillion = row['data_value'] / 1000000 if row['unit_mult'] == 6 else row['data_value']
            print(f"  {row['time_period']}: ${val_trillion:>6.2f}T")

        print("\n" + "="*60)
        print("GDP Growth Rate Timeseries (2018-2024)")
        print("="*60)
        ts_growth = await get_gdp_growth_rate_timeseries(session)
        for row in ts_growth:
            print(f"  {row['time_period']}: {row['data_value']:>5.1f}%")

        print("\n" + "="*60)
        print("PCE Current Dollars Timeseries (2018-2024)")
        print("="*60)
        ts_pce = await get_pce_current_dollars_timeseries(session)
        for row in ts_pce:
            val_trillion = row['data_value'] / 1000000 if row['unit_mult'] == 6 else row['data_value']
            print(f"  {row['time_period']}: ${val_trillion:>6.2f}T")

        print("\n" + "="*60)
        print("T10105 2024 Snapshot (Top 10 lines)")
        print("="*60)
        snapshot = await get_table_snapshot(session, "T10105", "2024")
        for row in snapshot[:10]:
            print(f"  Line {row['line_number']:>3}: ${row['data_value']:>12,.0f}  {row['line_description']}")

if __name__ == "__main__":
    asyncio.run(test_queries := test_nipa_queries())
