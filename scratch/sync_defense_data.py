import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.market_data_fetcher import MarketDataFetcher

async def sync_defense_data():
    async with AsyncSessionLocal() as db:
        fetcher = MarketDataFetcher(db)
        print("=" * 80)
        print("SYNCING DEFENSE MARKET DATA")
        print("=" * 80)
        
        # This will sync ITA, XAR, PPA, XLI from AV
        # and FX pairs from Frankfurter
        res = await fetcher.sync_market_data_sample(domain_id="defense_technology")
        print(f"Sync Results: {res}")
        print("\n" + "=" * 80)

if __name__ == "__main__":
    asyncio.run(sync_defense_data())
