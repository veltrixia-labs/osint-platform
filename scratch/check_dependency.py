import asyncio
from db.database import AsyncSessionLocal
from db.models import Dependency
from sqlalchemy import select, func

async def main():
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count(Dependency.id)))).scalar()
        print(f"Dependency count: {count}")

asyncio.run(main())
