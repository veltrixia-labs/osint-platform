import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.database import AsyncSessionLocal
from sqlalchemy import select
from db.models import MarketDataFetchLog

async def check():
    async with AsyncSessionLocal() as db:
        print("--- Recent Market Data Fetch Logs ---")
        stmt = select(MarketDataFetchLog).order_by(MarketDataFetchLog.started_at.desc()).limit(15)
        res = await db.execute(stmt)
        for l in res.scalars().all():
            print(f"[{l.started_at}] {l.job_name}: {l.status} (req={l.instruments_requested}, saved={l.rows_saved}, error={l.error_message})")

if __name__ == "__main__":
    asyncio.run(check())
