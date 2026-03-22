import asyncio
import os
import sys

# Add root to sys.path
sys.path.append(os.getcwd())

from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import Report

async def verify_reports():
    async with AsyncSessionLocal() as session:
        # 1. Total count
        stmt = select(Report)
        res = await session.execute(stmt)
        all_reports = res.scalars().all()
        print(f"Total reports in DB: {len(all_reports)}")
        
        # 2. Breakdown by type
        types = {}
        for r in all_reports:
            types[r.report_type] = types.get(r.report_type, 0) + 1
        print(f"Breakdown by type: {types}")
        
        # 3. Check what stays after filter
        filtered = [r for r in all_reports if "system_diagnostic" not in (r.report_type or "")]
        print(f"Reports after 'NOT LIKE system_diagnostic%' filter: {len(filtered)}")
        for r in filtered[:5]:
            print(f" - [{r.report_type}] {r.title}")

if __name__ == "__main__":
    asyncio.run(verify_reports())
