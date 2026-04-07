"""
scripts/seed_admin.py
Creates test accounts for various tiers to verify access control.
Usage: python scripts/seed_admin.py
"""
import asyncio
import uuid
import sys
import os
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import AsyncSessionLocal
from db.models import AnalystProfile
from api.auth import get_password_hash
from sqlalchemy.future import select

async def seed_test_accounts():
    print("[Seed] Initializing test accounts...")
    
    test_users = [
        {
            "email": "admin@veltrixia.com",
            "password": "adminpassword123",
            "role": "admin",
            "tier": "enterprise",
            "chat_id": "admin_test"
        },
        {
            "email": "expert@veltrixia.com",
            "password": "expertpassword123",
            "role": "analyst",
            "tier": "experts",
            "chat_id": "expert_test"
        },
        {
            "email": "pro@veltrixia.com",
            "password": "propassword123",
            "role": "analyst",
            "tier": "pro",
            "chat_id": "pro_test"
        },
        {
            "email": "free@veltrixia.com",
            "password": "freepassword123",
            "role": "analyst",
            "tier": "free",
            "chat_id": "free_test"
        }
    ]

    async with AsyncSessionLocal() as session:
        for u in test_users:
            stmt = select(AnalystProfile).where(AnalystProfile.email == u["email"])
            existing = (await session.execute(stmt)).scalar_one_or_none()
            
            if existing:
                print(f"[Seed] User {u['email']} already exists. Skipping.")
                continue
                
            new_user = AnalystProfile(
                id=uuid.uuid4(),
                email=u["email"],
                hashed_password=get_password_hash(u["password"]),
                user_role=u["role"],
                subscription_tier=u["tier"],
                telegram_chat_id=u["chat_id"],
                is_active=True,
                is_email_verified=True,
                created_at=datetime.now(timezone.utc),
                subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=365)
            )
            session.add(new_user)
            print(f"[Seed] Created {u['role']} user: {u['email']} (Tier: {u['tier']})")
            
        await session.commit()
    print("[Seed] Done.")

if __name__ == "__main__":
    asyncio.run(seed_test_accounts())
