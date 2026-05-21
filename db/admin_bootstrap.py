"""Admin email resolution and idempotent bootstrap sync."""
import logging
import os
import secrets
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api.password_utils import get_password_hash
from db.models import AnalystProfile

logger = logging.getLogger(__name__)


def render_admin_env_configured() -> bool:
    """True when both ADMIN_PASSWORD and a resolvable admin email are set."""
    admin_password = (os.getenv("ADMIN_PASSWORD") or "").strip()
    if not admin_password:
        return False
    return bool(resolve_admin_email())


def _safe_compare_text(left: str, right: str) -> bool:
    """Constant-time string compare; never raises on length/encoding edge cases."""
    if not left or not right:
        return False
    try:
        a = left.encode("utf-8")
        b = right.encode("utf-8")
        if len(a) != len(b):
            return False
        return secrets.compare_digest(a, b)
    except Exception:
        return False


def credentials_match_render_admin(email: str, password: str) -> bool:
    """
    Constant-time check against Render env ADMIN_EMAIL / ADMIN_PASSWORD.
    No-op when env vars are unset (never matches).
    """
    if not email or not password:
        return False
    admin_password = (os.getenv("ADMIN_PASSWORD") or "").strip()
    if not admin_password:
        return False
    admin_email = resolve_admin_email()
    if not admin_email:
        return False
    email_norm = (email or "").strip().lower()
    if not _safe_compare_text(email_norm, admin_email):
        return False
    return _safe_compare_text(password, admin_password)


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

    try:
        admin_email = resolve_admin_email()
    except Exception as exc:
        logger.error("ADMIN_BOOTSTRAP: invalid admin email config: %s", exc)
        return False

    if not admin_email:
        logger.warning("ADMIN_BOOTSTRAP: could not resolve admin email. Skipping.")
        return False

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


async def login_via_render_admin_env(
    db: AsyncSession,
    email: str,
    password: str,
) -> Optional[AnalystProfile]:
    """
    Approach A: env credentials match → sync admin row in DB → return profile for JWT issuance.
    Never raises — login route treats None as normal auth fallback.
    """
    try:
        if not credentials_match_render_admin(email, password):
            return None
        if not await ensure_bootstrap_admin(db):
            logger.error("ADMIN_LOGIN: bootstrap sync failed for %s", resolve_admin_email())
            return None
        admin_email = resolve_admin_email()
        user = (
            await db.execute(select(AnalystProfile).where(AnalystProfile.email == admin_email))
        ).scalar_one_or_none()
        if user:
            user.user_role = "admin"
            user.is_admin = True
            user.is_active = True
            await db.commit()
            await db.refresh(user)
        return user
    except Exception as exc:
        logger.error("ADMIN_LOGIN: unexpected error for %s: %s", email, exc, exc_info=True)
        return None
