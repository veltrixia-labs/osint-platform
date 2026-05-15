import asyncio
import sys
import os
from datetime import datetime, timezone
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import SystemMetric
from sqlalchemy import select

async def check_metrics():
    async with AsyncSessionLocal() as db:
        print("=" * 80)
        print("SYSTEM METRICS AUDIT")
        print("=" * 80)
        
        stmt = select(SystemMetric)
        res = await db.execute(stmt)
        metrics = res.scalars().all()
        
        for m in metrics:
            print(f"  {m.metric_key:30}: {m.metric_value} (Updated: {m.updated_at})")

if __name__ == "__main__":
    asyncio.run(check_metrics())
