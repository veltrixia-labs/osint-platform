import asyncio
from db.database import AsyncSessionLocal
from db.models import AnalystProfile
from sqlalchemy.future import select

async def get_user():
    async with AsyncSessionLocal() as session:
        stmt = select(AnalystProfile).limit(1)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            print(f"USER_FOUND: {user.telegram_chat_id}")
        else:
            print("NO_USER")

if __name__ == "__main__":
    asyncio.run(get_user())
