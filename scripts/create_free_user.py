import asyncio
import os
import sys

# Ensure project root is in path for imports
sys.path.append(os.getcwd())

from db.database import AsyncSessionLocal
from db.models import AnalystProfile
from api.auth import get_password_hash
from sqlalchemy.future import select

async def create_free_user():
    username = "free_test_user"
    password = "free_test_user"
    
    async with AsyncSessionLocal() as session:
        # Final check to avoid duplicates (though uniquely constrained)
        stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == username)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        
        if existing:
            print(f"USER_EXISTS: {username} already in database.")
            return

        hashed_pw = get_password_hash(password)
        new_user = AnalystProfile(
            telegram_chat_id=username,
            hashed_password=hashed_pw,
            user_role="analyst",
            is_active=True,
            subscription_tier="free"
        )
        
        session.add(new_user)
        try:
            await session.commit()
            print(f"SUCCESS: Created {username} with Free tier.")
        except Exception as e:
            await session.rollback()
            print(f"ERROR: Failed to create user: {e}")

if __name__ == "__main__":
    asyncio.run(create_free_user())
