"""
Test script for ExternalDataRepository.

Verifies idempotent saving (Upsert) of various external data types:
1. Timeseries (FRED)
2. Trade Flows (Comtrade)
3. Industry Stats (Census/BEA)
4. Fetch Logs
"""

import asyncio
import sys
import os
from datetime import date

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from data_sources.external_data_repository import ExternalDataRepository
from sqlalchemy import select, func
from db.models import (
    ExternalDataSeries, 
    ExternalObservation, 
    ExternalTradeFlow, 
    ExternalIndustryStat, 
    ExternalDataFetchLog
)

async def run_test():
    async with AsyncSessionLocal() as db:
        repo = ExternalDataRepository(db)
        
        print("=" * 60)
        print("EXTERNAL REPOSITORY TEST")
        print("=" * 60)

        # 1. Test Fetch Log
        print("\n[1] Testing Fetch Log...")
        log = await repo.create_fetch_log(source="test_source", job_name="test_job")
        log_id = log.id
        print(f"  Created log: {log_id}")
        
        await repo.finish_fetch_log(log, status="success", rows_fetched=100, rows_saved=50)
        print("  Finished log.")

        # 2. Test Series Upsert
        print("\n[2] Testing Series Upsert (FRED)...")
        series = await repo.upsert_series(
            source="fred",
            series_id="FEDFUNDS",
            name="Effective Federal Funds Rate",
            unit="percent",
            frequency="monthly",
            category="monetary_policy"
        )
        await db.flush()
        print(f"  Upserted series: {series.series_id} (ID: {series.id})")

        # 3. Test Observation Upsert
        print("\n[3] Testing Observation Upsert...")
        obs1 = await repo.upsert_observation(
            series=series,
            source="fred",
            series_id="FEDFUNDS",
            date_val="2024-01-01",
            value="5.33",
            raw_json={"original": "5.33"}
        )
        await db.flush()
        print(f"  Upserted observation: {obs1.date} = {obs1.value}")

        # 4. Test Idempotency (Same Observation)
        print("\n[4] Testing Idempotency (Same Observation)...")
        obs2 = await repo.upsert_observation(
            series=series,
            source="fred",
            series_id="FEDFUNDS",
            date_val="2024-01-01",
            value=5.34, # Update value
            raw_json={"original": "5.34 updated"}
        )
        await db.flush()
        print(f"  Re-upserted (Updated) observation: {obs2.date} = {obs2.value}")
        
        # Check count
        count_stmt = select(func.count()).select_from(ExternalObservation).where(
            ExternalObservation.series_id == "FEDFUNDS",
            ExternalObservation.date == date(2024, 1, 1)
        )
        count = (await db.execute(count_stmt)).scalar()
        print(f"  Count for FEDFUNDS at 2024-01-01: {count} (Should be 1)")

        # 5. Test Trade Flow Upsert
        print("\n[5] Testing Trade Flow Upsert (Comtrade)...")
        flow = await repo.upsert_trade_flow(
            source="comtrade",
            reporter_id="392",
            reporter_name="Japan",
            partner_id="0",
            partner_name="World",
            flow_type="M",
            commodity_id="8542",
            commodity_name="Semiconductors",
            year=2023,
            period="2023",
            trade_value=28604003278.0,
            unit="USD"
        )
        await db.flush()
        print(f"  Upserted trade flow: JP -> World (8542) = {flow.trade_value}")

        # 6. Test Industry Stat Upsert
        print("\n[6] Testing Industry Stat Upsert (Census)...")
        stat = await repo.upsert_industry_stat(
            source="census",
            dataset="cbp",
            geo_id="06",
            geo_name="California",
            industry_id="00",
            industry_name="Total",
            metric_name="EMP",
            year=2022,
            period="A",
            value=16032440.0,
            unit="employees"
        )
        await db.flush()
        print(f"  Upserted industry stat: CA (Total EMP) = {stat.value}")

        # Final Commit
        await db.commit()
        print("\n" + "=" * 60)
        print("Test completed and committed.")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
