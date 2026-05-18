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
    email = "free_test_user@veltrixia.local"
    password = "free_test_user"

    async with AsyncSessionLocal() as session:
        stmt = select(AnalystProfile).where(AnalystProfile.email == email)
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing:
            print(f"USER_EXISTS: {email} already in database.")
            return

        hashed_pw = get_password_hash(password)
        new_user = AnalystProfile(
            email=email,
            hashed_password=hashed_pw,
            user_role="analyst",
            is_active=True,
            subscription_tier="free",
        )
        
        session.add(new_user)
        try:
            await session.commit()
            print(f"SUCCESS: Created {email} with Free tier.")
        except Exception as e:
            await session.rollback()
            print(f"ERROR: Failed to create user: {e}")

if __name__ == "__main__":
    asyncio.run(create_free_user())
