import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.market_data_fetcher import MarketDataFetcher

async def sync_global_market_data():
    async with AsyncSessionLocal() as db:
        fetcher = MarketDataFetcher(db)
        print("=" * 80)
        print("SYNCING GLOBAL MARKET DATA")
        print("=" * 80)
        
        # We want to prioritize TLT, GLD, IWM, SHY
        # The fetcher.sync_alpha_vantage_sample(domain_id="global_market_intelligence") 
        # will sync all symbols defined for that domain in the catalog.
        
        res = await fetcher.sync_market_data_sample(domain_id="global_market_intelligence")
        print(f"Sync Results: {res}")
        print("\n" + "=" * 80)

if __name__ == "__main__":
    asyncio.run(sync_global_market_data())
