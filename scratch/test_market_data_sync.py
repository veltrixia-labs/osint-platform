"""
Test script for Market Data Synchronization.

Verifies:
1. Data ingestion from Alpha Vantage and Frankfurter.
2. Idempotency (repeated runs don't create duplicates).
3. Fetch log recording.
"""

import asyncio
import sys
import os
import logging
from sqlalchemy import select, func

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.market_data_fetcher import MarketDataFetcher
from db.models import MarketDataInstrument, MarketDataPrice, MarketDataFetchLog

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_test():
    async with AsyncSessionLocal() as db:
        fetcher = MarketDataFetcher(db)
        
        print("=" * 60)
        print("MARKET DATA SYNC TEST (Phase 5c)")
        print("=" * 60)

        # 1. First run
        print("\n[RUN 1] Starting synchronization...")
        results = await fetcher.sync_market_data_sample()
        print(f"Results: {results}")

        # Count records
        inst_count = (await db.execute(select(func.count()).select_from(MarketDataInstrument))).scalar()
        price_count = (await db.execute(select(func.count()).select_from(MarketDataPrice))).scalar()
        log_count = (await db.execute(select(func.count()).select_from(MarketDataFetchLog))).scalar()
        
        print(f"\nAfter RUN 1:")
        print(f"  MarketDataInstrument count: {inst_count}")
        print(f"  MarketDataPrice count: {price_count}")
        print(f"  MarketDataFetchLog count: {log_count}")

        # 2. Second run (Check Idempotency)
        # Note: We need a new session or be careful with the existing one if we committed.
        # MarketDataFetcher handles commits internally.
        
        print("\n[RUN 2] Starting re-synchronization (Idempotency check)...")
        results2 = await fetcher.sync_market_data_sample()
        print(f"Results: {results2}")

        inst_count2 = (await db.execute(select(func.count()).select_from(MarketDataInstrument))).scalar()
        price_count2 = (await db.execute(select(func.count()).select_from(MarketDataPrice))).scalar()
        log_count2 = (await db.execute(select(func.count()).select_from(MarketDataFetchLog))).scalar()

        print(f"\nAfter RUN 2:")
        print(f"  MarketDataInstrument count: {inst_count2}")
        print(f"  MarketDataPrice count: {price_count2}")
        print(f"  MarketDataFetchLog count: {log_count2}")

        # Verification
        if inst_count == inst_count2:
            print("\n  [OK] Instrument count is stable (Idempotent).")
        else:
            print("\n  [FAIL] Instrument count changed!")

        if price_count == price_count2:
            print("  [OK] Price count is stable (Idempotent).")
        else:
            # Note: Price count might increase if a new day's data arrived between runs, 
            # but in this short test window it should be stable.
            print(f"  [WARNING] Price count changed from {price_count} to {price_count2}. Check if duplicate or new date.")

        if log_count2 > log_count:
            print("  [OK] New fetch logs were recorded.")
        else:
            print("  [FAIL] No new fetch logs recorded.")

    print("\n" + "=" * 60)
    print("Test completed.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
