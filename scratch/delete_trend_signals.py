import asyncio
from sqlalchemy import delete
from db.database import AsyncSessionLocal
from db.models import TrendSignal

async def main():
    async with AsyncSessionLocal() as session:
        await session.execute(delete(TrendSignal))
        await session.commit()
        print("deleted TrendSignal")

asyncio.run(main())