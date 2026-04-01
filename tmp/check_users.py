import asyncio
import os
import sys
from sqlalchemy import select

# Ensure we can import from project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AnalystProfile

async def check_users():
    print("--- Database User Diagnostic ---")
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(AnalystProfile)
            result = await session.execute(stmt)
            users = result.scalars().all()
            
            if not users:
                print("No users found in the database.")
            else:
                print(f"Found {len(users)} users:")
                for user in users:
                    print(f" - ID: {user.telegram_chat_id}, Role: {user.user_role}, Tier: {user.subscription_tier}")
                    # DO NOT print hashed_password for security, but we know it's there
        except Exception as e:
            print(f"Error accessing database: {e}")

if __name__ == "__main__":
    asyncio.run(check_users())
