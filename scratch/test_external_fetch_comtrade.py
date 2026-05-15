"""
Test script for UN Comtrade fetch job.

Verifies:
1. Data fetching from UN Comtrade API for selected commodities and countries.
2. Saving to ExternalTradeFlow table via ExternalDataRepository.
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
    ExternalTradeFlow, 
    ExternalDataFetchLog
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_stats(db):
    flow_count = (await db.execute(select(func.count()).select_from(ExternalTradeFlow))).scalar()
    log_count = (await db.execute(select(func.count()).select_from(ExternalDataFetchLog))).scalar()
    return flow_count, log_count

async def run_test():
    async with AsyncSessionLocal() as db:
        fetcher = ExternalDataFetcher(db)
        
        print("=" * 60)
        print("COMTRADE FETCH JOB TEST (RUN 1)")
        print("=" * 60)

        result1 = await fetcher.sync_comtrade()
        print(f"\nRun 1 Result: {result1}")

        f1, l1 = await get_stats(db)
        print(f"Stats after Run 1:")
        print(f"  Trade Flows: {f1}")
        print(f"  Fetch Logs: {l1}")

        print("\n" + "=" * 60)
        print("COMTRADE FETCH JOB TEST (RUN 2 - IDEMPOTENCY CHECK)")
        print("=" * 60)

        result2 = await fetcher.sync_comtrade()
        print(f"\nRun 2 Result: {result2}")

        f2, l2 = await get_stats(db)
        print(f"Stats after Run 2:")
        print(f"  Trade Flows: {f2} (Change: {f2-f1})")
        print(f"  Fetch Logs: {l2} (Change: {l2-l1})")

        if f2 == f1:
            print("\nSUCCESS: Idempotency verified. No duplicate trade flows.")
        else:
            print("\nWARNING: Counts changed on second run. Check for duplicates.")

        # Print a sample record
        print("\nSample Record from DB:")
        sample_stmt = select(ExternalTradeFlow).limit(1)
        sample = (await db.execute(sample_stmt)).scalar()
        if sample:
            print(f"  {sample.reporter_name} -> {sample.partner_name} ({sample.commodity_id}) {sample.year}: {sample.trade_value} {sample.unit}")

        print("\n" + "=" * 60)
        print("Test completed.")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
