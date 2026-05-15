"""
Test script for ExternalDataFetcher jobs.

Runs the synchronization jobs for FRED, BLS, and World Bank,
then verifies the data in the database and checks for idempotency on re-run.
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
    ExternalDataSeries, 
    ExternalObservation, 
    ExternalDataFetchLog
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_stats(db):
    series_count = (await db.execute(select(func.count()).select_from(ExternalDataSeries))).scalar()
    obs_count = (await db.execute(select(func.count()).select_from(ExternalObservation))).scalar()
    log_count = (await db.execute(select(func.count()).select_from(ExternalDataFetchLog))).scalar()
    return series_count, obs_count, log_count

async def run_test():
    async with AsyncSessionLocal() as db:
        fetcher = ExternalDataFetcher(db)
        
        print("=" * 60)
        print("EXTERNAL FETCH JOBS TEST (RUN 1)")
        print("=" * 60)

        # Run individual syncs
        await fetcher.sync_fred()
        await fetcher.sync_bls()
        await fetcher.sync_worldbank()

        s1, o1, l1 = await get_stats(db)
        print(f"\nStats after Run 1:")
        print(f"  Series: {s1}")
        print(f"  Observations: {o1}")
        print(f"  Fetch Logs: {l1}")

        print("\n" + "=" * 60)
        print("EXTERNAL FETCH JOBS TEST (RUN 2 - IDEMPOTENCY CHECK)")
        print("=" * 60)

        # Run again
        await fetcher.sync_fred()
        await fetcher.sync_bls()
        await fetcher.sync_worldbank()

        s2, o2, l2 = await get_stats(db)
        print(f"\nStats after Run 2:")
        print(f"  Series: {s2} (Change: {s2-s1})")
        print(f"  Observations: {o2} (Change: {o2-o1})")
        print(f"  Fetch Logs: {l2} (Change: {l2-l1})")

        if s2 == s1 and o2 == o1:
            print("\nSUCCESS: Idempotency verified. No duplicate series or observations.")
        else:
            print("\nWARNING: Counts changed on second run. Check for duplicates.")

        print("\n" + "=" * 60)
        print("Test completed.")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
