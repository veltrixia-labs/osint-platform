import asyncio
import os
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import AsyncSessionLocal
from db.models import AnalystProfile
from api.auth import get_password_hash

async def bootstrap():
    """
    Creates the first admin user in the production database.
    Environment variables:
    - ADMIN_CHAT_ID: Internal identifier for the first admin (default 'admin')
    - ADMIN_PASSWORD: Plaintext password to be hashed (default 'password123')
    """
    chat_id = os.getenv("ADMIN_CHAT_ID", "admin")
    password = os.getenv("ADMIN_PASSWORD", "password123")
    
    print(f"Starting bootstrap for user: {chat_id}")
    
    async with AsyncSessionLocal() as session:
        # Check if any user already exists to prevent accidental duplicates
        stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == chat_id)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            print(f"ABORT: User '{chat_id}' already exists in the database.")
            return

        # Create the first analyst with admin role and enterprise tier
        admin = AnalystProfile(
            id=uuid4(),
            telegram_chat_id=chat_id,
            hashed_password=get_password_hash(password),
            user_role="admin",
            subscription_tier="enterprise",
            is_active=True
        )
        
        session.add(admin)
        await session.commit()
        print(f"SUCCESS: Created admin user '{chat_id}' with role 'admin' and tier 'enterprise'.")

if __name__ == "__main__":
    # Ensure current directory is in PYTHONPATH so imports work
    import sys
    if "." not in sys.path:
        sys.path.append(".")
        
    asyncio.run(bootstrap())
