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
        await db.commit()
        logger.info("ADMIN_SEED: Created admin user 'admin' successfully.")

    except Exception as e:
        await db.rollback()
        logger.error(f"ADMIN_SEED: Error during admin seeding: {e}")
