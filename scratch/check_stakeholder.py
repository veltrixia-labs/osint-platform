import asyncio
from db.database import AsyncSessionLocal
from db.models import Stakeholder
from sqlalchemy import select, func

async def main():
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count(Stakeholder.id)))).scalar()
        print(f"Stakeholder count: {count}")

asyncio.run(main())
