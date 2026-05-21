"""
api/routes/system.py
System endpoints:
  GET /api/system/health, /api/system/usage, /api/system/diagnostics
  GET /api/metrics, /api/health, /api/status, /api/version, /api/reports/sample
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.future import select
from sqlalchemy import desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime, timezone, timedelta
import json
import logging

from db.models import AlertLog, AlertDelivery, AnalystProfile, Report, SystemMetric
from db.database import get_db
from api.gating import (
    get_effective_tier, get_plan_limits, get_watchlist_limit, get_alert_limit,
    can_access_report_type, get_allowed_topics, get_restricted_topics, TIER_GUEST
)
from api.auth import get_current_user_from_access, get_optional_current_user, blacklist_manager, resolve_optional_user

router = APIRouter(tags=["system"])
logger = logging.getLogger(__name__)

# Set externally from api/main.py
COMMIT_HASH = "7.5-FINAL-SYNC"
DEPLOY_TIMESTAMP = "2026-04-04T13:50:00Z"


@router.get("/system/usage")
async def get_usage(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[tuple] = Depends(get_optional_current_user)
):
    """Return real-time usage statistics against the user's plan limits."""
    # current_user is (user, session_id, version) or None
    user = resolve_optional_user(current_user)
    tier = await get_effective_tier(user)
    limits = get_plan_limits(tier)

    if not user:
        return {
            "tier": tier,
            "alerts": {"used": 0, "limit": limits["alerts_per_day"]},
            "keywords": {"used": 0, "limit": limits["watchlist_keywords"]},
            "topics": {"allowed": get_allowed_topics(tier), "restricted": get_restricted_topics(tier)},
            "reports": {"daily": True, "monthly": False},
        }

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    alerts_stmt = (
        select(func.count(AlertDelivery.id))
        .where(
            AlertDelivery.analyst_id == user.id,
            AlertDelivery.status == "delivered",
            AlertDelivery.delivered_at >= today_start,
        )
    )
    alerts_used = (await db.execute(alerts_stmt)).scalar() or 0

    kw = user.watch_keywords
    keywords_used = len(kw) if isinstance(kw, list) else 0

    alert_limit = limits["alerts_per_day"]
    reports_cfg = limits["reports"]

    return {
        "tier": tier,
        "alerts": {
            "used": alerts_used,
            "limit": alert_limit if alert_limit != "unlimited" else -1,
        },
        "keywords": {
            "used": keywords_used,
            "limit": limits["watchlist_keywords"],
        },
        "topics": {
            "allowed": get_allowed_topics(tier),
            "restricted": get_restricted_topics(tier),
        },
        "reports": {
            "daily": True,
            "monthly": can_access_report_type(tier, "monthly"),
        },
    }


@router.get("/system/health")
async def get_system_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[tuple] = Depends(get_optional_current_user)
):
    user = resolve_optional_user(current_user)
    user_role = user.user_role if user else "guest"

    # Caching
    cache_key = f"metrics:{user_role}"
    if await blacklist_manager._is_redis_available():
        try:
            cached = await blacklist_manager.redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except:
            pass

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    total_stmt = select(func.count(AlertLog.id)).where(AlertLog.triggered_at >= week_ago)
    total = (await db.execute(total_stmt)).scalar() or 0

    reviewed_stmt = select(func.count(AlertLog.id)).where(AlertLog.triggered_at >= week_ago, AlertLog.feedback_score.isnot(None))
    reviewed = (await db.execute(reviewed_stmt)).scalar() or 0

    suppressed_stmt = select(func.count(AlertLog.id)).where(AlertLog.triggered_at >= week_ago, AlertLog.suppressed == True)
    suppressed = (await db.execute(suppressed_stmt)).scalar() or 0

    high_fidelity_stmt = select(func.count(AlertLog.id)).where(AlertLog.triggered_at >= week_ago, AlertLog.is_high_fidelity == True)
    high_fidelity = (await db.execute(high_fidelity_stmt)).scalar() or 0

    health_data = {
        "review_rate": round(reviewed / total if total > 0 else 0, 2),
        "suppression_ratio": round(suppressed / (total + suppressed) if (total + suppressed) > 0 else 0, 2),
        "total_alerts": total,
        "high_fidelity_count": high_fidelity
    }

    if user_role == "admin":
        trigger_stmt = select(
            AlertLog.trigger_type,
            func.avg(AlertLog.feedback_score)
        ).where(AlertLog.triggered_at >= week_ago, AlertLog.feedback_score.isnot(None)).group_by(AlertLog.trigger_type).order_by(desc(func.avg(AlertLog.feedback_score))).limit(5)
        top_triggers = (await db.execute(trigger_stmt)).all()

        health_data.update({
            "total_incidents": total,
            "top_performing_triggers": [{"type": t[0], "avg_feedback": round(t[1], 2)} for t in top_triggers],
            "system_status": "operational"
        })
    else:
        health_data.update({
            "status_summary": "Active",
            "last_week_total": total
        })

    # Store in Cache (300s TTL)
    if await blacklist_manager._is_redis_available():
        try:
            await blacklist_manager.redis_client.setex(cache_key, 300, json.dumps(health_data))
        except:
            pass

    return health_data


@router.get("/system/diagnostics")
async def get_system_diagnostics(
    current_user: tuple = Depends(get_current_user_from_access),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve diagnostic reports for internal debugging (Admin only)."""
    user, _, _ = current_user
    if user.user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    stmt = select(Report).where(Report.report_type == "system_diagnostic").order_by(Report.created_at.desc()).limit(10)
    results = (await db.execute(stmt)).scalars().all()

    return [
        {
            "id": str(r.id),
            "title": r.title,
            "content": r.content_markdown,
            "created_at": r.created_at.isoformat() if hasattr(r.created_at, 'isoformat') else r.created_at
        } for r in results
    ]


@router.get("/health")
async def public_health_check():
    """Unauthenticated health endpoint for Render's port scan."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/metrics")
async def get_all_metrics(db: AsyncSession = Depends(get_db)):
    """Expose system metrics for dashboard/monitoring."""
    stmt = select(SystemMetric)
    result = await db.execute(stmt)
    metrics = result.scalars().all()
    return {m.metric_key: m.metric_value for m in metrics}
