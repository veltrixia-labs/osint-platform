import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Union
from fastapi import HTTPException, Depends
from db.models import AnalystProfile
from sqlalchemy.ext.asyncio import AsyncSession
from api.auth import get_current_user_from_access

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Tier Constants
# ──────────────────────────────────────────────────────────────────────────────

TIER_FREE = "free"
TIER_PRO = "pro"
TIER_ENTERPRISE = "enterprise"

TIER_ORDER = [TIER_FREE, TIER_PRO, TIER_ENTERPRISE]

GRACE_PERIOD_DAYS = 3

# ──────────────────────────────────────────────────────────────────────────────
# Centralized Plan Limits  (single source of truth)
# ──────────────────────────────────────────────────────────────────────────────

PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    TIER_FREE: {
        "alerts_per_day": 5,
        "watchlist_keywords": 3,
        "allowed_topics": ["global", "market", "community"],
        "reports": ["daily"],
    },
    TIER_PRO: {
        "alerts_per_day": 100,
        "watchlist_keywords": 20,
        "allowed_topics": "all",
        "reports": ["daily", "monthly"],
    },
    TIER_ENTERPRISE: {
        "alerts_per_day": "unlimited",
        "watchlist_keywords": 100,
        "allowed_topics": "all",
        "reports": "all",
    },
}

# Complete list of all topic codes in the platform
ALL_TOPIC_CODES = [
    "global", "market", "community",
    "energy_resource_risk", "global_market_intelligence",
    "ai_semiconductor_intelligence", "crypto_geopolitics",
    "defense_technology", "supply_chain_intelligence",
]

# ──────────────────────────────────────────────────────────────────────────────
# Tier Resolution
# ──────────────────────────────────────────────────────────────────────────────

async def get_effective_tier(user: AnalystProfile) -> str:
    """Determine the user's active tier, handling expiration and grace period."""
    if not user.subscription_expires_at:
        return user.subscription_tier or TIER_FREE

    now = datetime.now(timezone.utc)
    expires = user.subscription_expires_at
    # SQLite returns naive datetimes; normalize to UTC-aware for comparison
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires + timedelta(days=GRACE_PERIOD_DAYS):
        return TIER_FREE

    return user.subscription_tier or TIER_FREE

# ──────────────────────────────────────────────────────────────────────────────
# Plan Limit Helpers  (all APIs must use these — no inline logic)
# ──────────────────────────────────────────────────────────────────────────────

def get_plan_limits(tier: str) -> Dict[str, Any]:
    """Return the full limits dict for *tier*."""
    return PLAN_LIMITS.get(tier, PLAN_LIMITS[TIER_FREE])


def get_watchlist_limit(tier: str) -> int:
    """Max watchlist keywords for *tier*."""
    return get_plan_limits(tier)["watchlist_keywords"]


def get_alert_limit(tier: str) -> Union[int, str]:
    """Max alerts/day for *tier*.  Returns ``"unlimited"`` for Enterprise."""
    return get_plan_limits(tier)["alerts_per_day"]


def is_topic_allowed(tier: str, topic_code: str) -> bool:
    """Return True if *topic_code* is accessible under *tier*."""
    allowed = get_plan_limits(tier)["allowed_topics"]
    if allowed == "all":
        return True
    return topic_code in allowed


def get_allowed_topics(tier: str) -> List[str]:
    """Return the list of topic codes the tier can access."""
    allowed = get_plan_limits(tier)["allowed_topics"]
    if allowed == "all":
        return list(ALL_TOPIC_CODES)
    return list(allowed)


def get_restricted_topics(tier: str) -> List[str]:
    """Return topic codes that the tier CANNOT access."""
    allowed = get_plan_limits(tier)["allowed_topics"]
    if allowed == "all":
        return []
    return [t for t in ALL_TOPIC_CODES if t not in allowed]


def can_access_report_type(tier: str, report_type: str) -> bool:
    """Return True if *report_type* is available under *tier*."""
    reports = get_plan_limits(tier)["reports"]
    if reports == "all":
        return True
    return report_type in reports


def can_add_watchlist_keywords(tier: str, new_total: int) -> bool:
    """Return True if the resulting keyword count is within the tier limit."""
    return new_total <= get_watchlist_limit(tier)


def can_receive_more_alerts(tier: str, delivered_today_count: int) -> bool:
    """Return True if the user can still receive alerts today."""
    limit = get_alert_limit(tier)
    if limit == "unlimited":
        return True
    return delivered_today_count < limit

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI Dependencies
# ──────────────────────────────────────────────────────────────────────────────

def requires_tier(min_tier: str):
    """FastAPI dependency to enforce a minimum subscription tier."""
    async def tier_checker(current_user: tuple = Depends(get_current_user_from_access)):
        user, _, _ = current_user
        effective = await get_effective_tier(user)

        if TIER_ORDER.index(effective) < TIER_ORDER.index(min_tier):
            raise HTTPException(
                status_code=403,
                detail=f"Subscription upgrade required. Minimum tier: {min_tier}"
            )
        return user
    return tier_checker


def requires_role(required_role: str):
    """FastAPI dependency to enforce a specific user role (independent of tier)."""
    async def role_checker(current_user: tuple = Depends(get_current_user_from_access)):
        user, _, _ = current_user
        if user.user_role != required_role:
            raise HTTPException(
                status_code=403,
                detail=f"Role permission required: {required_role}"
            )
        return user
    return role_checker

# ──────────────────────────────────────────────────────────────────────────────
# Legacy wrappers (kept for backward-compat with generation layer)
# ──────────────────────────────────────────────────────────────────────────────

async def can_generate_report(user: AnalystProfile, report_type: str) -> bool:
    """Gate report generation based on tier — delegates to can_access_report_type."""
    tier = await get_effective_tier(user)
    return can_access_report_type(tier, report_type)


async def get_watchlist_limit_for_user(user: AnalystProfile) -> int:
    """Return watchlist limit for a user object (resolves tier internally)."""
    tier = await get_effective_tier(user)
    return get_watchlist_limit(tier)
