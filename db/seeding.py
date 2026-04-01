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
        # 1. Handle 'admin'
        stmt_admin = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == "admin")
        res_admin = await db.execute(stmt_admin)
        admin = res_admin.scalar_one_or_none()

        if admin:
            admin.hashed_password = get_password_hash(admin_password)
            logger.info("[Antigravity] Admin user password synchronized with environment.")
        else:
            hashed_pw_admin = get_password_hash(admin_password)
            admin = AnalystProfile(
                telegram_chat_id="admin",
                hashed_password=hashed_pw_admin,
                user_role="admin",
                is_active=True,
                subscription_tier="enterprise"
            )
            db.add(admin)

        # 2. Handle 'testuser'
        stmt_test = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == "testuser")
        res_test = await db.execute(stmt_test)
        testuser = res_test.scalar_one_or_none()

        if not testuser:
            test_pw = get_password_hash("testuser")
            testuser = AnalystProfile(
                telegram_chat_id="testuser",
                hashed_password=test_pw,
                user_role="analyst",
                is_active=True,
                subscription_tier="enterprise"
            )
            db.add(testuser)
        
        await db.commit()
        logger.info("[Antigravity] Seed synchronization for all users: SUCCESS.")

    except Exception as e:
        await db.rollback()
        logger.error(f"ADMIN_SEED: Error during admin seeding: {e}")
