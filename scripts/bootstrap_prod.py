import asyncio
import os
import sys
from uuid import uuid4

from sqlalchemy import select

from api.auth import get_password_hash
from db.admin_bootstrap import resolve_admin_email
from db.database import AsyncSessionLocal
from db.models import AnalystProfile


async def bootstrap():
    """
    Creates the first admin user in the production database (email-based).

    Environment variables:
    - ADMIN_EMAIL or ADMIN_CHAT_ID: admin login email (see resolve_admin_email)
    - ADMIN_PASSWORD: plaintext password to be hashed
    """
    admin_email = resolve_admin_email()
    password = os.getenv("ADMIN_PASSWORD", "password123")

    print(f"Starting bootstrap for admin email: {admin_email}")

    async with AsyncSessionLocal() as session:
        stmt = select(AnalystProfile).where(AnalystProfile.email == admin_email)
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing:
            print(f"ABORT: User with email '{admin_email}' already exists.")
            return

        admin = AnalystProfile(
            id=uuid4(),
            email=admin_email,
            hashed_password=get_password_hash(password),
            user_role="admin",
            is_admin=True,
            subscription_tier="enterprise",
            is_active=True,
        )

        session.add(admin)
        await session.commit()
        print(f"SUCCESS: Created admin '{admin_email}' (is_admin=true).")


if __name__ == "__main__":
    if "." not in sys.path:
        sys.path.append(".")

    asyncio.run(bootstrap())
