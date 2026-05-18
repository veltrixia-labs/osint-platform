import logging

from db.admin_bootstrap import ensure_bootstrap_admin

logger = logging.getLogger(__name__)


async def seed_admin(db):
    """Idempotently ensure the bootstrap admin exists (delegates to admin_bootstrap)."""
    ok = await ensure_bootstrap_admin(db)
    if ok:
        logger.info("ADMIN_SEED: success.")
    else:
        logger.warning("ADMIN_SEED: bootstrap did not complete.")
