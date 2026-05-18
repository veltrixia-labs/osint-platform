import logging
import os

from sqlalchemy.future import select

from api.auth import get_password_hash
from db.admin_bootstrap import resolve_admin_email
from db.models import AnalystProfile

logger = logging.getLogger(__name__)


async def seed_admin(db):
    """
    Idempotently ensure the bootstrap admin exists (email + password from env).

    Environment:
    - ADMIN_PASSWORD (required for create/sync)
    - ADMIN_EMAIL or ADMIN_CHAT_ID (see resolve_admin_email)
    """
    admin_password = os.getenv("ADMIN_PASSWORD", "admin")
    if not admin_password:
        logger.warning("ADMIN_SEED: ADMIN_PASSWORD not set. Skipping.")
        return

    admin_email = resolve_admin_email()

    try:
        stmt = select(AnalystProfile).where(AnalystProfile.email == admin_email)
        admin = (await db.execute(stmt)).scalar_one_or_none()

        if not admin:
            legacy_stmt = select(AnalystProfile).where(
                AnalystProfile.telegram_chat_id == (os.getenv("ADMIN_CHAT_ID") or "admin")
            )
            admin = (await db.execute(legacy_stmt)).scalar_one_or_none()
            if admin and not admin.email:
                admin.email = admin_email

        if admin:
            admin.hashed_password = get_password_hash(admin_password)
            admin.is_admin = True
            admin.user_role = "admin"
            admin.is_active = True
            if not admin.subscription_tier:
                admin.subscription_tier = "enterprise"
            logger.info("ADMIN_SEED: synchronized admin profile for %s", admin_email)
        else:
            admin = AnalystProfile(
                email=admin_email,
                hashed_password=get_password_hash(admin_password),
                user_role="admin",
                is_admin=True,
                is_active=True,
                subscription_tier="enterprise",
            )
            db.add(admin)
            logger.info("ADMIN_SEED: created admin profile for %s", admin_email)

        await db.commit()
        logger.info("ADMIN_SEED: success.")
    except Exception as e:
        await db.rollback()
        logger.error("ADMIN_SEED: failed: %s", e)
