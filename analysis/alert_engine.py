"""
analysis/alert_engine.py
Phase 33 — Alert Delivery Gating

Enforces daily alert limits per analyst tier.
All limit logic delegates to api.gating helpers.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import AlertDelivery, AlertLog, AnalystProfile
from api.gating import get_effective_tier, can_receive_more_alerts, get_alert_limit

logger = logging.getLogger(__name__)


async def get_delivered_today_count(db: AsyncSession, analyst_id) -> int:
    """Count successfully delivered alerts for *analyst_id* today (UTC)."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    stmt = (
        select(func.count(AlertDelivery.id))
        .where(
            AlertDelivery.analyst_id == analyst_id,
            AlertDelivery.status == "delivered",
            AlertDelivery.delivered_at >= today_start,
        )
    )
    return (await db.execute(stmt)).scalar() or 0


async def try_deliver_alert(
    db: AsyncSession,
    alert_log: AlertLog,
    analyst: AnalystProfile,
    relevance_score: float = 0.0,
) -> bool:
    """
    Attempt to deliver *alert_log* to *analyst*.

    Returns True if a delivery record was created, False if the alert was
    suppressed because the analyst's daily limit has been reached.

    Suppressed alerts are **not** inserted as successful deliveries and are
    logged with their suppression reason.
    """
    tier = await get_effective_tier(analyst)
    delivered_today = await get_delivered_today_count(db, analyst.id)

    if not can_receive_more_alerts(tier, delivered_today):
        # ── Suppression logging ──────────────────────────────────────────
        logger.info(
            "Alert suppressed for analyst %s (tier=%s): "
            "delivered_today=%d, limit=%s, reason=daily_limit_reached",
            analyst.id,
            tier,
            delivered_today,
            get_alert_limit(tier),
        )

        # Record a suppressed delivery (NOT counted as "delivered")
        suppressed = AlertDelivery(
            alert_log_id=alert_log.id,
            analyst_id=analyst.id,
            status="suppressed",
            relevance_score=relevance_score,
            suppression_reason="daily_limit_reached",
        )
        db.add(suppressed)
        await db.flush()
        return False

    # ── Normal delivery ──────────────────────────────────────────────────
    delivery = AlertDelivery(
        alert_log_id=alert_log.id,
        analyst_id=analyst.id,
        status="delivered",
        relevance_score=relevance_score,
    )
    db.add(delivery)
    await db.flush()
    return True
