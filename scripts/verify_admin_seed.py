import asyncio
import os
import sys
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import AnalystProfile

async def verify_admin_seed():
    """
    Verifies that the admin user exists and has correct attributes.
    """
    print("Verifying Admin Seed...")
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == "admin")
            result = await session.execute(stmt)
            admin = result.scalar_one_or_none()

            if not admin:
                print("FAILURE: Admin user 'admin' not found in database.")
                return False

            print(f"SUCCESS: Admin user found (ID: {admin.id})")
            print(f"  - Role: {admin.user_role}")
            print(f"  - Active: {admin.is_active}")
            print(f"  - Subscription: {admin.subscription_tier}")
            
            if admin.user_role != "admin":
                print(f"FAILURE: Expected role 'admin', found '{admin.user_role}'")
                return False
            
            if not admin.is_active:
                print("FAILURE: Admin user is not active.")
                return False

            print("\nAdmin user is correctly configured.")
            return True

        except Exception as e:
            print(f"ERROR during verification: {e}")
            return False

if __name__ == "__main__":
    # Add project root to sys.path for db/models import
    sys.path.append(os.getcwd())
    
    success = asyncio.run(verify_admin_seed())
    sys.exit(0 if success else 1)
