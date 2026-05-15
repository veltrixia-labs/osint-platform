import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.database import AsyncSessionLocal
from sqlalchemy import select
from db.models import MarketDataInstrument, MarketDataPrice

async def check():
    async with AsyncSessionLocal() as db:
        print("--- Registered Instruments ---")
        stmt = select(MarketDataInstrument)
        res = await db.execute(stmt)
        for inst in res.scalars().all():
            print(f"[{inst.provider}] {inst.symbol}: {inst.asset_class} (Domains: {inst.domain_ids})")
            
        print("\n--- Latest Prices (Sample) ---")
        stmt = select(MarketDataPrice).order_by(MarketDataPrice.date.desc()).limit(10)
        res = await db.execute(stmt)
        for p in res.scalars().all():
            print(f"{p.symbol}: {p.close} on {p.date}")

if __name__ == "__main__":
    asyncio.run(check())
