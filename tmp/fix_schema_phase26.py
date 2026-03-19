import asyncio
from db.database import engine
from db.models import Base

async def fix():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Schema updated successfully (AlertLog.suppressed added if missing).")

if __name__ == "__main__":
    asyncio.run(fix())
