"""Admin email resolution and idempotent bootstrap sync."""
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api.auth import get_password_hash
from db.models import AnalystProfile

logger = logging.getLogger(__name__)


def resolve_admin_email() -> str:
    """
    Resolve bootstrap admin email from environment.

    - ADMIN_EMAIL: preferred explicit address
    - ADMIN_CHAT_ID: if contains '@', treated as email; else ``{id}@admin.veltrixia.local``
    """
    explicit = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    if explicit:
        return explicit

    chat_id = (os.getenv("ADMIN_CHAT_ID") or "admin").strip().lower()
    if "@" in chat_id:
        return chat_id
    return f"{chat_id}@admin.veltrixia.local"


async def ensure_bootstrap_admin(db: AsyncSession) -> bool:
    """
    Create or update the bootstrap admin using ADMIN_EMAIL / ADMIN_CHAT_ID and ADMIN_PASSWORD.

    Safe when ``is_admin`` already exists in DB (column pre-created or from a prior partial deploy).
    Returns True on success, False when ADMIN_PASSWORD is missing or sync failed.
    """
    admin_password = (os.getenv("ADMIN_PASSWORD") or "").strip()
    if not admin_password:
        logger.warning("ADMIN_BOOTSTRAP: ADMIN_PASSWORD not set. Skipping.")
        return False

    admin_email = resolve_admin_email()
    legacy_chat_id = (os.getenv("ADMIN_CHAT_ID") or "admin").strip()

    try:
        admin = (
            await db.execute(
                select(AnalystProfile).where(AnalystProfile.email == admin_email)
            )
        ).scalar_one_or_none()

        if not admin and legacy_chat_id:
            admin = (
                await db.execute(
                    select(AnalystProfile).where(
                        AnalystProfile.telegram_chat_id == legacy_chat_id
                    )
                )
            ).scalar_one_or_none()
            if admin:
                admin.email = admin_email

        if admin:
            admin.email = admin_email
            admin.hashed_password = get_password_hash(admin_password)
            admin.is_admin = True
            admin.user_role = "admin"
            admin.is_active = True
            if not admin.subscription_tier:
                admin.subscription_tier = "enterprise"
            logger.info("ADMIN_BOOTSTRAP: synchronized admin %s", admin_email)
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
            logger.info("ADMIN_BOOTSTRAP: created admin %s", admin_email)

        await db.commit()
        return True
    except Exception as exc:
        await db.rollback()
        logger.error("ADMIN_BOOTSTRAP: failed for %s: %s", admin_email, exc)
        return False
