import os
import logging
from sqlalchemy.future import select
from db.models import AnalystProfile
from api.auth import get_password_hash

logger = logging.getLogger(__name__)

async def seed_admin(db):
    """
    Idempotently seeds the admin user if it doesn't exist.
    """
    admin_password = os.getenv("ADMIN_PASSWORD", "admin")
    if not admin_password:
        # This shouldn't happen now with the default, but keeping check for clarity
        logger.warning("ADMIN_SEED: ADMIN_PASSWORD not set and no default. Skipping.")
        return

    try:
        # Check if admin already exists
        stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == "admin")
        result = await db.execute(stmt)
        admin = result.scalar_one_or_none()

        if admin:
            logger.info("ADMIN_SEED: Admin user 'admin' already exists.")
            return

        # Create admin user
        hashed_pw = get_password_hash(admin_password)
        new_admin = AnalystProfile(
            telegram_chat_id="admin",
            hashed_password=hashed_pw,
            user_role="admin",
            is_active=True,
            subscription_tier="enterprise"
        )
        db.add(new_admin)

        # Create testuser
        test_pw = get_password_hash("testuser")
        new_test = AnalystProfile(
            telegram_chat_id="testuser",
            hashed_password=test_pw,
            user_role="analyst",
            is_active=True,
            subscription_tier="enterprise"
        )
        db.add(new_test)

        await db.commit()
        logger.info("ADMIN_SEED: Created admin user 'admin' successfully.")

    except Exception as e:
        await db.rollback()
        logger.error(f"ADMIN_SEED: Error during admin seeding: {e}")
