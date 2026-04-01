import asyncio
import os
import sys
from sqlalchemy import select

# Ensure we can import from project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AnalystProfile
from api.auth import get_password_hash

async def reset_admin_password():
    print("--- Admin Password Force Reset ---")
    async with AsyncSessionLocal() as session:
        try:
            # 1. Targeted check for 'admin'
            stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == "admin")
            result = await session.execute(stmt)
            admin = result.scalar_one_or_none()
            
            if not admin:
                print("Error: 'admin' user not found. Seeding new admin...")
                new_admin = AnalystProfile(
                    telegram_chat_id="admin",
                    hashed_password=get_password_hash("admin"),
                    user_role="admin",
                    is_active=True,
                    subscription_tier="enterprise"
                )
                session.add(new_admin)
            else:
                print(f"User 'admin' found. Updating password to 'admin'...")
                admin.hashed_password = get_password_hash("admin")
            
            await session.commit()
            print("Successfully updated 'admin' password to 'admin'.")
            
        except Exception as e:
            await session.rollback()
            print(f"Error resetting password: {e}")

if __name__ == "__main__":
    asyncio.run(reset_admin_password())
