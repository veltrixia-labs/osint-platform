import asyncio
import os
import sys
sys.path.append(os.getcwd())
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import ExternalPost

async def check_posts():
    async with AsyncSessionLocal() as session:
        stmt = select(ExternalPost)
        results = (await session.execute(stmt)).scalars().all()
        print(f"Total Threads Posts in DB: {len(results)}")
        for p in results:
            print(f"- ID: {p.id}, Platform: {p.platform}, Status: {p.status}, Published: {p.published_at}")

if __name__ == "__main__":
    asyncio.run(check_posts())
