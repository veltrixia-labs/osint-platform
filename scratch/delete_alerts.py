import asyncio
from sqlalchemy import delete
from db.database import AsyncSessionLocal
from db.models import AlertLog

async def main():
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AlertLog))
        await session.commit()
        print("deleted AlertLog")

asyncio.run(main())