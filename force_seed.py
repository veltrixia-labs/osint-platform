import asyncio
from db.database import AsyncSessionLocal
from db.models import AnalystProfile
from api.auth import get_password_hash
from sqlalchemy.future import select

async def seed_users():
    async with AsyncSessionLocal() as session:
        for username in ["admin", "testuser"]:
            stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == username)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            
            hashed = get_password_hash(username) # password same as username for test
            if existing:
                existing.hashed_password = hashed
                print(f"Updated {username}")
            else:
                new_user = AnalystProfile(
                    telegram_chat_id=username,
                    hashed_password=hashed,
                    user_role="admin" if username == "admin" else "analyst",
                    is_active=True,
                    subscription_tier="enterprise"
                )
                session.add(new_user)
                print(f"Created {username}")
        await session.commit()

if __name__ == "__main__":
    asyncio.run(seed_users())
