import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Union
from fastapi import HTTPException, Depends
from db.models import AnalystProfile
from sqlalchemy.ext.asyncio import AsyncSession
from api.auth import get_current_user_from_access, get_optional_current_user

logger = logging.getLogger(__name__)

from db.enums import PlanTier, ReportType, TIER_ORDER, is_tier_sufficient

# ──────────────────────────────────────────────────────────────────────────────
# Tier Constants (Aliased for backward-compat where needed)
# ──────────────────────────────────────────────────────────────────────────────

TIER_FREE = PlanTier.FREE.value
TIER_PRO = PlanTier.PRO.value
TIER_EXPERTS = PlanTier.EXPERTS.value
TIER_ENTERPRISE = PlanTier.ENTERPRISE.value

GRACE_PERIOD_DAYS = 3

# ──────────────────────────────────────────────────────────────────────────────
# Centralized Plan Limits (single source of truth)
# ──────────────────────────────────────────────────────────────────────────────

# Pseudo-tier for Guests (Unauthenticated)
TIER_GUEST = "guest"

PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    TIER_GUEST: {
        "alerts_per_day": 3,
        "watchlist_keywords": 0,
        "allowed_topics": "all",
        "reports": "all",
    },
    PlanTier.FREE.value: {
        "alerts_per_day": 3,
        "watchlist_keywords": 0,
        "allowed_topics": "all",
        "reports": "all",
    },
    PlanTier.PRO.value: {
        "alerts_per_day": 100,
        "watchlist_keywords": 20,
        "allowed_topics": "all",
        "reports": "all",
    },
    PlanTier.EXPERTS.value: {
        "alerts_per_day": "unlimited",
        "watchlist_keywords": 100,
        "allowed_topics": "all",
        "reports": "all",
    },
    PlanTier.ENTERPRISE.value: {
        "alerts_per_day": "unlimited",
        "watchlist_keywords": "unlimited",
        "allowed_topics": "all",
        "reports": "all",
        "custom_topics": True,
    },
}

# Complete list of all topic codes in the platform
ALL_TOPIC_CODES = [
    "global",
    "energy_resource_risk", "global_market_intelligence",
    "ai_semiconductor_intelligence", "crypto_geopolitics",
    "defense_technology", "supply_chain_intelligence",
]

# ──────────────────────────────────────────────────────────────────────────────
# Tier Resolution
# ──────────────────────────────────────────────────────────────────────────────

async def get_effective_tier(user: Optional[AnalystProfile]) -> str:
    """Determine the user's active tier, handling expiration, grace period, and Guests."""
    if not user:
        return TIER_GUEST
        
    if not user.subscription_expires_at:
        return user.subscription_tier or TIER_FREE

    now = datetime.now(timezone.utc)
    expires = user.subscription_expires_at
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
    return PLAN_LIMITS.get(tier, PLAN_LIMITS[TIER_GUEST])


def get_watchlist_limit(tier: str) -> int:
    """Max watchlist keywords for *tier*."""
    return get_plan_limits(tier)["watchlist_keywords"]


def get_alert_limit(tier: str) -> Union[int, str]:
    """Max alerts/day for *tier*.  Returns ``"unlimited"`` for Enterprise."""
    return get_plan_limits(tier)["alerts_per_day"]


def is_topic_allowed(tier: str, topic_code: str) -> bool:
    """TEMPORARY: Returns True for all topics (De-gating phase)."""
    return True


def get_allowed_topics(tier: str) -> List[str]:
    """Return the list of all topic codes (De-gating phase)."""
    return list(ALL_TOPIC_CODES)


def get_restricted_topics(tier: str) -> List[str]:
    """Return an empty list (De-gating phase)."""
    return []


def can_access_report_type(tier: str, report_type: str) -> bool:
    """TEMPORARY: Returns True for all report types (De-gating phase)."""
    return True


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
    async def tier_checker(current_user: Optional[tuple] = Depends(get_optional_current_user)):
        # current_user is (user, session_id, version) or None
        user = current_user[0] if current_user else None
        effective = await get_effective_tier(user)

        # 1. Check for Guest Access
        # Allow Guest if the required tier is FREE (Public access)
        if effective == TIER_GUEST:
            if min_tier == PlanTier.FREE.value:
                return None # Valid guest access
            else:
                raise HTTPException(
                    status_code=401,
                    detail="Account required for this intelligence domain. Please sign in or upgrade."
                )

        # 2. Check for Tier Sufficiency (403)
        try:
            if TIER_ORDER.index(effective) < TIER_ORDER.index(min_tier):
                raise HTTPException(
                    status_code=403,
                    detail=f"Subscription upgrade required. Minimum tier: {min_tier}"
                )
        except ValueError:
             raise HTTPException(status_code=403, detail="Invalid tier configuration")
             
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


def _gate_cascading_impacts(tier: str, impacts: list) -> list:
    # [Dev Phase Override] Always return full impacts to verify system completion
    return impacts
