import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from sqlalchemy import select
from db.models import Report

async def check():
    async with AsyncSessionLocal() as db:
        stmt = select(Report).where(Report.plan_required == 'pro')
        res = await db.execute(stmt)
        reports = res.scalars().all()
        print(f"Total Pro Reports found in DB: {len(reports)}")
        for r in reports:
            print(f" - {r.id}: {r.title} (Type: {r.report_type})")

if __name__ == "__main__":
    asyncio.run(check())
