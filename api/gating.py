import uuid
import logging
import contextvars
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Union
from fastapi import HTTPException, Depends
from db.models import AnalystProfile
from sqlalchemy.ext.asyncio import AsyncSession
from api.auth import get_current_user_from_access, get_optional_current_user, resolve_optional_user
import os

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

def is_admin_profile(user: Optional[AnalystProfile]) -> bool:
    """True when the profile has admin privileges (column or legacy user_role)."""
    if not user:
        return False
    if bool(getattr(user, "is_admin", False)):
        return True
    return (user.user_role or "").lower() == "admin"


def is_production_env() -> bool:
    """True only when ENV is explicitly 'production'. All dev overrides are gated off here."""
    return os.environ.get("ENV", "development").lower() == "production"


# Valid tier strings a non-prod dev override may resolve to.
_VALID_DEV_TIERS = {t.value for t in PlanTier}

# ──────────────────────────────────────────────────────────────────────────────
# Per-request Dev Tier Override (X-Dev-Tier header)
# ──────────────────────────────────────────────────────────────────────────────
# Set by the DevTierHeaderMiddleware from the request's `X-Dev-Tier` header, which
# the frontend LOCAL DEV TIER toggle injects in local dev. This lets backend
# payloads match the toggled UI tier per-request. HONORED IN NON-PROD ONLY — the
# middleware never sets it in production, so prod always falls through to real auth.
_request_dev_tier: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_dev_tier", default=None
)


def set_request_dev_tier(raw_tier: Optional[str]) -> None:
    """Store the per-request X-Dev-Tier override (normalized; invalid/blank → None)."""
    tier = (raw_tier or "").strip().lower()
    _request_dev_tier.set(tier if tier in _VALID_DEV_TIERS else None)


def get_request_dev_tier() -> Optional[str]:
    """Return the per-request dev-tier override, or None."""
    return _request_dev_tier.get()


async def get_effective_tier(user: Optional[AnalystProfile]) -> str:
    """Determine the user's active tier, handling expiration, grace period, and Guests."""
    # Local Dev Override for UI testing (MUST be disabled in production).
    if not is_production_env():
        # 1. Per-request X-Dev-Tier header — synced with the frontend LOCAL DEV
        #    TIER toggle so data payloads match the UI tier exactly.
        req_tier = get_request_dev_tier()
        if req_tier:
            return req_tier
        # 2. Legacy env-based override (ALLOW_DEV_TIER_OVERRIDE + LOCAL_DEV_TIER).
        allow_dev_override = os.environ.get("ALLOW_DEV_TIER_OVERRIDE", "false").lower() == "true"
        dev_tier = os.environ.get("LOCAL_DEV_TIER")
        if allow_dev_override and dev_tier:
            return dev_tier.lower()

    if not user:
        return TIER_GUEST

    if is_admin_profile(user):
        manual = (getattr(user, "manual_tier", None) or "").strip().lower()
        if manual:
            return manual
        
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
    """Check if the tier is allowed to access the specific topic code."""
    # Global topic and NULL/None are always allowed
    if not topic_code or topic_code.lower() == "global":
        return True
    
    # All other strategic topics require at least PRO tier
    return is_tier_sufficient(tier, PlanTier.PRO.value)


def get_allowed_topics(tier: str) -> List[str]:
    """Return the list of all topic codes (De-gating phase)."""
    return list(ALL_TOPIC_CODES)


def get_restricted_topics(tier: str) -> List[str]:
    """Return an empty list (De-gating phase)."""
    return []


def can_access_report_type(tier: str, report_type: str) -> bool:
    """Gate report access: Daily (Free), Weekly (Pro), Monthly (Expert)."""
    # System mapping for report types
    REPORT_TYPE_MIN_TIER = {
        ReportType.DAILY.value: PlanTier.FREE.value,
        ReportType.WEEKLY.value: PlanTier.PRO.value,
        ReportType.MONTHLY.value: PlanTier.EXPERTS.value,
        ReportType.SYSTEM_DIAGNOSTIC.value: PlanTier.ENTERPRISE.value,
    }
    
    required = REPORT_TYPE_MIN_TIER.get(report_type.lower(), PlanTier.FREE.value)
    return is_tier_sufficient(tier, required)


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
    async def tier_checker(current_user=Depends(get_optional_current_user)):
        user = resolve_optional_user(current_user)
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


# ──────────────────────────────────────────────────────────────────────────────
# Dev Mode + Payload Tiering ($19 Basic vs $99 Institutional)
# ──────────────────────────────────────────────────────────────────────────────

# When DEV_MODE is true, EVERY request is elevated to the full ("institutional")
# payload regardless of the caller's tier — restrictions are bypassed for auditing.
# RELEASE-AUDIT DEFAULT: ON. Per the architect's mandate the platform is currently
# presented as a fully unlocked development version, so paywall payload-shaping
# (evidence truncation, AI-brief stripping, cascading-impact gating) is bypassed
# globally. Set env DEV_MODE=false to re-enable real tier gating for launch.
DEV_MODE = os.environ.get("DEV_MODE", "true").lower() == "true"

# Tier (and above) that receives the full, unrestricted alert payload. Lowered from
# EXPERTS to PRO: Expert is not sold (see stripe_service.ALLOWED_CHECKOUT_TIERS), so
# leaving the threshold there meant a paying Pro subscriber received exactly the payload
# a Free user did. Measured over the 30 rows GET /api/alerts returns: evidence entries
# visible to Pro go from 51 to 209.
INSTITUTIONAL_MIN_TIER = PlanTier.PRO.value

# Secondary sources a caller below INSTITUTIONAL_MIN_TIER may see before truncation.
BASIC_MAX_EVIDENCE = 3


def gate_alert_payload(alert: Dict[str, Any], tier: str) -> Dict[str, Any]:
    """Shape a serialized alert for the caller's tier.

    Returns the FULL payload untouched when DEV_MODE is on OR the caller is at or
    above INSTITUTIONAL_MIN_TIER (currently PRO). Below that — guest and free —
    evidence_list is truncated to BASIC_MAX_EVIDENCE and `description` is dropped.
    No mosaic / locked flags are set; this is a pure payload-shape decision, not a
    visible lock.
    """
    if DEV_MODE or is_tier_sufficient(tier, INSTITUTIONAL_MIN_TIER):
        return alert
    gated = dict(alert)
    ev = gated.get("evidence_list")
    if isinstance(ev, list) and len(ev) > BASIC_MAX_EVIDENCE:
        gated["evidence_list"] = ev[:BASIC_MAX_EVIDENCE]
    # NOT an AI brief. `description` is written at jobs/alert_manager.py:668 from
    # TrendSignal.description, whose five assignment sites in analysis/trend_engine.py
    # are three string literals (:332, :395, :434) and three copies of
    # rc.representative_title (:476, :513, :536). No LLM is in that chain. Measured:
    # 58 of 58 rows carry the key, 14 are non-empty, 12 of those are byte-identical to
    # target_label, and none contains prose.
    gated["description"] = None
    gated["is_partial"] = True
    return gated


def _gate_cascading_impacts(tier: str, impacts: list) -> list:
    """
    Control the depth of cascading impact chains:
    - Guest/Free: 0 (No impacts)
    - Pro: Max depth = 2
    - Expert/Enterprise: Unlimited (999)
    """
    if is_tier_sufficient(tier, PlanTier.EXPERTS.value):
        return impacts
        
    if is_tier_sufficient(tier, PlanTier.PRO.value):
        # Filter for first and second order impacts (depth <= 2)
        return [i for i in impacts if (i.get("level") or i.get("order") or 1) <= 2]
    
    # Guest/Free users see 0 cascading impacts
    return []
