"""
Test script for BEA and Census industry statistics fetch jobs.

Verifies:
1. Data fetching from BEA (GDPbyIndustry) and Census (CBP).
2. Saving to ExternalIndustryStat table via ExternalDataRepository.
3. Idempotency on second run.
"""

import asyncio
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.external_data_fetcher import ExternalDataFetcher
from sqlalchemy import select, func
from db.models import (
    ExternalIndustryStat, 
    ExternalDataFetchLog
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_stats(db):
    stat_count = (await db.execute(select(func.count()).select_from(ExternalIndustryStat))).scalar()
    log_count = (await db.execute(select(func.count()).select_from(ExternalDataFetchLog))).scalar()
    return stat_count, log_count

async def run_test():
    async with AsyncSessionLocal() as db:
        fetcher = ExternalDataFetcher(db)
        
        print("=" * 60)
        print("INDUSTRY STATS FETCH JOB TEST (RUN 1)")
        print("=" * 60)

        # Run individual syncs
        bea_res = await fetcher.sync_bea_industry_stats()
        census_res = await fetcher.sync_census_cbp()
        
        print(f"\nBEA Result: {bea_res}")
        print(f"Census Result: {census_res}")

        s1, l1 = await get_stats(db)
        print(f"\nStats after Run 1:")
        print(f"  Industry Stats: {s1}")
        print(f"  Fetch Logs: {l1}")

        print("\n" + "=" * 60)
        print("INDUSTRY STATS FETCH JOB TEST (RUN 2 - IDEMPOTENCY CHECK)")
        print("=" * 60)

        # Run again
        await fetcher.sync_bea_industry_stats()
        await fetcher.sync_census_cbp()

        s2, l2 = await get_stats(db)
        print(f"\nStats after Run 2:")
        print(f"  Industry Stats: {s2} (Change: {s2-s1})")
        print(f"  Fetch Logs: {l2} (Change: {l2-l1})")

        if s2 == s1:
            print("\nSUCCESS: Idempotency verified. No duplicate industry stats.")
        else:
            print("\nWARNING: Counts changed on second run. Check for duplicates.")

        # Print samples
        print("\nSamples from DB:")
        bea_sample = (await db.execute(select(ExternalIndustryStat).where(ExternalIndustryStat.source == "bea").limit(1))).scalar()
        if bea_sample:
            print(f"  BEA: {bea_sample.industry_name} | {bea_sample.metric_name} ({bea_sample.year}): {bea_sample.value} {bea_sample.unit}")
            
        census_sample = (await db.execute(select(ExternalIndustryStat).where(ExternalIndustryStat.source == "census").limit(1))).scalar()
        if census_sample:
            print(f"  Census: {census_sample.geo_name} | {census_sample.metric_name} ({census_sample.year}): {census_sample.value} {census_sample.unit}")

        print("\n" + "=" * 60)
        print("Test completed.")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
