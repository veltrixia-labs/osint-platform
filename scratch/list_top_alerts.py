import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.database import AsyncSessionLocal
from sqlalchemy import select, desc
from db.models import AlertLog

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(AlertLog).order_by(desc(AlertLog.intelligence_score)).limit(10))
        for a in res.scalars().all():
            print(f"{a.id} | {a.target_label} | {a.severity} | {a.intelligence_score} | {a.topic}")

if __name__ == "__main__":
    asyncio.run(check())
