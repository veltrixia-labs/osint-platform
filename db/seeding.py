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
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_password:
        logger.warning("ADMIN_SEED: ADMIN_PASSWORD environment variable not set. Skipping admin seeding.")
        return

    try:
        # 1. Admin Account
        stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == "admin")
        result = await db.execute(stmt)
        admin = result.scalar_one_or_none()

        if not admin:
            admin_password = os.getenv("ADMIN_PASSWORD", "admin") # Default to admin if not set
            hashed_pw = get_password_hash(admin_password)
            new_admin = AnalystProfile(
                telegram_chat_id="admin",
                hashed_password=hashed_pw,
                user_role="admin",
                is_active=True,
                subscription_tier="enterprise"
            )
            db.add(new_admin)
            logger.info("ADMIN_SEED: Created admin user.")

        # 2. Test Account
        stmt_test = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == "testuser")
        res_test = await db.execute(stmt_test)
        test_user = res_test.scalar_one_or_none()

        if not test_user:
            test_pw = get_password_hash("testuser")
            new_test = AnalystProfile(
                telegram_chat_id="testuser",
                hashed_password=test_pw,
                user_role="analyst",
                is_active=True,
                subscription_tier="enterprise"
            )
            db.add(new_test)
            logger.info("ADMIN_SEED: Created testuser.")

        await db.commit()

    except Exception as e:
        await db.rollback()
        logger.error(f"ADMIN_SEED: Error during seeding: {e}")
