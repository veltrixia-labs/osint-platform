"""
API Routes for Pro Structural Briefs.

Provides endpoints for Pro and Expert users to access advanced 
structural impact reports.
"""

import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from typing import Any, Dict, Optional, Tuple
import uuid

from db.database import AsyncSessionLocal
from db.models import Report, AnalystProfile, AlertLog, SystemicFragilityLog
from api.gating import get_effective_tier, is_tier_sufficient, TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE, TIER_GUEST
from api.auth import get_optional_current_user
from reports.text_encoding import sanitize_unicode_tree
from jobs.pro_structural_reports import pro_structural_report_filters
from jobs.pro_structural_dedup import latest_reports_per_topic

router = APIRouter(prefix="/pro", tags=["Pro Reports"])

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def get_current_tier(
    current_user: Optional[Any] = Depends(get_optional_current_user),
) -> str:
    user = None
    if current_user is not None:
        user = current_user[0] if isinstance(current_user, tuple) else current_user
    return await get_effective_tier(user)


async def require_authenticated_pro_tier(
    current_user: Optional[Any] = Depends(get_optional_current_user),
) -> str:
    """Pro Brief detail requires a logged-in user with Pro tier or above, or an active dev override."""
    user = current_user[0] if isinstance(current_user, tuple) and current_user else current_user
    tier = await get_effective_tier(user)
    
    allowed = [TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE]
    
    if user is None:
        import os
        env_name = os.environ.get("ENV", "development").lower()
        allow_dev = os.environ.get("ALLOW_DEV_TIER_OVERRIDE", "false").lower() == "true"
        if not (env_name != "production" and allow_dev and tier in allowed):
            raise HTTPException(status_code=401, detail="Authentication required")

    if tier in (TIER_GUEST, "free") or tier not in allowed:
        raise HTTPException(
            status_code=403,
            detail="Pro or Expert subscription required for this analysis.",
        )
    return tier

@router.get("/reports")
async def get_pro_reports(
    response: Response,
    db: AsyncSession = Depends(get_db),
    tier: str = Depends(get_current_tier),
):
    """
    Fetch a list of recent Pro Structural Briefs.
    Gated to Pro, Expert, and Enterprise tiers.
    """
    # Allowed tiers for Pro reports
    allowed_tiers = [TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE]
    
    for key, value in _NO_STORE_HEADERS.items():
        response.headers[key] = value

    if tier not in allowed_tiers:
        return []

    stmt = (
        select(Report)
        .where(*pro_structural_report_filters())
        .order_by(desc(Report.created_at))
        .limit(50)
    )
    
    result = await db.execute(stmt)
    reports = latest_reports_per_topic(result.scalars().all())

    return [
        {
            "id": str(r.id),
            "title": sanitize_unicode_tree(r.title),
            "report_type": r.report_type,
            "topic": r.topic_code,
            "plan_required": r.plan_required,
            "is_premium": r.is_premium,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "teaser_md": sanitize_unicode_tree(r.teaser_md),
        }
        for r in reports
    ]


@router.get("/map/signals")
async def get_pro_map_signals(
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    tier: str = Depends(get_current_tier),
):
    """
    Geo-ready alert signals for Pro map clients: only rows with lat/lng.
    """
    allowed_tiers = [TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE]
    if tier not in allowed_tiers:
        raise HTTPException(status_code=403, detail="Pro subscription required for map signals.")

    cap = max(1, min(limit, 500))
    stmt = (
        select(AlertLog)
        .where(AlertLog.location_lat.isnot(None), AlertLog.location_lng.isnot(None))
        .order_by(desc(AlertLog.triggered_at))
        .limit(cap)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    signals = [
        {
            "id": str(a.id),
            "target_label": a.target_label,
            "topic": a.topic,
            "severity": a.severity,
            "trigger_type": a.trigger_type,
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
            "intensity": a.intensity,
            "intelligence_score": a.intelligence_score,
            "fidelity_score": a.fidelity_score,
            "status": a.status,
            "lat": a.location_lat,
            "lng": a.location_lng,
        }
        for a in rows
    ]
    return {"signals": signals, "count": len(signals)}


@router.get("/reports/{report_id}")
async def get_pro_report_detail(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    tier: str = Depends(require_authenticated_pro_tier),
):
    """
    Fetch the full Markdown content of a specific Pro Structural Brief (auth + Pro required).
    """
    try:
        report_uuid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report ID format.")

    stmt = select(Report).where(Report.id == report_uuid)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    # ── Strict Plan Gating (same helper and idiom as reports.get_report_detail) ──
    # The previous check compared report.plan_required to the literal "pro" and could
    # never fire: require_authenticated_pro_tier has already constrained tier to
    # [pro, experts, enterprise], so `tier not in allowed_tiers` was always False. A
    # pro subscriber could therefore read an experts-tier report in full.
    plan_required = report.plan_required or "free"
    if not is_tier_sufficient(tier, plan_required):
        raise HTTPException(
            status_code=403,
            detail=f"Subscription upgrade required. This report requires the '{plan_required}' plan."
        )

    return {
        "id": str(report.id),
        "title": sanitize_unicode_tree(report.title),
        "report_type": report.report_type,
        "topic": report.topic_code,
        "plan_required": report.plan_required,
        "is_premium": report.is_premium,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "content_markdown": sanitize_unicode_tree(report.content_markdown),
        "structured_payload": sanitize_unicode_tree(report.structured_payload),
    }


# ── Systemic Fragility history (phase-space trajectory) ──────────────────

_MAX_FRAGILITY_HISTORY_DAYS = 90  # hard cap so a 9999-day request can't sweep the table

# Process-local cache for latest_spatial_contagion. Keyed by domain_id; TTL
# 300s (5 minutes). The frontend polls fragility-history every 3s — without
# this cache, every poll would JOIN with Reports table just to ship the same
# unchanged spatial graph. Reports flip slowly (~30min cycle), so 5min TTL
# is comfortably tighter than the real refresh rate.
_SPATIAL_CACHE_TTL_SECONDS = 300
_SPATIAL_CACHE: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}


async def _get_cached_latest_spatial(
    db: AsyncSession, domain_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Return the latest `spatial_contagion` JSON block for ``domain_id``,
    backed by a 5-minute in-process cache.

    Lookup strategy:
      1. Cache hit & fresh → return cached value (may be None if last DB
         lookup found nothing — we cache misses too, so the JOIN doesn't
         keep firing for domains that have no reports yet).
      2. Cache miss / expired → SELECT the newest pro_structural Report
         for the domain, extract structured_payload.spatial_contagion,
         memoise, return.
    """
    now = time.time()
    cached = _SPATIAL_CACHE.get(domain_id)
    if cached is not None and (now - cached[0]) < _SPATIAL_CACHE_TTL_SECONDS:
        return cached[1]

    stmt = (
        select(Report.structured_payload)
        .where(
            Report.report_type == "pro_structural",
            Report.topic_code == domain_id,
        )
        .order_by(desc(Report.created_at))
        .limit(1)
    )
    raw_payload = (await db.execute(stmt)).scalar_one_or_none()
    spatial: Optional[Dict[str, Any]] = None
    if isinstance(raw_payload, dict):
        candidate = raw_payload.get("spatial_contagion")
        if isinstance(candidate, dict) and isinstance(candidate.get("nodes"), list):
            spatial = candidate
    _SPATIAL_CACHE[domain_id] = (now, spatial)
    return spatial


@router.get("/domains/{domain_id}/fragility-history")
async def get_fragility_history(
    domain_id: str,
    days: int = Query(7, ge=1, le=_MAX_FRAGILITY_HISTORY_DAYS),
    db: AsyncSession = Depends(get_db),
    tier: str = Depends(get_current_tier),
):
    """
    Return the Systemic Fragility trajectory for a domain over the last
    ``days`` days (default 7, hard-capped at 90).

    Each point is one pipeline computation cycle:
        { timestamp, entropy_index, viscosity_coefficient, label,
          phase_transition_warning, sample_size }

    Ordered by timestamp ASCENDING so frontends can plot the path through
    2D phase space without re-sorting.
    """
    allowed_tiers = [TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE]
    if tier not in allowed_tiers:
        raise HTTPException(
            status_code=403,
            detail="Pro subscription required for fragility history.",
        )

    domain = (domain_id or "").strip()
    if not domain:
        raise HTTPException(status_code=400, detail="domain_id is required")

    since = datetime.now(timezone.utc) - timedelta(days=int(days))
    stmt = (
        select(SystemicFragilityLog)
        .where(
            SystemicFragilityLog.domain_id == domain,
            SystemicFragilityLog.timestamp >= since,
        )
        .order_by(SystemicFragilityLog.timestamp.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    series = [
        {
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "entropy_index": round(float(r.entropy_index), 4),
            "viscosity_coefficient": round(float(r.viscosity_coefficient), 4),
            "label": r.label,
            "phase_transition_warning": bool(r.phase_transition_warning),
            "sample_size": r.sample_size,
        }
        for r in rows
    ]

    # Lightweight aggregate stats so the frontend doesn't recompute.
    warning_count = sum(1 for p in series if p["phase_transition_warning"])
    last = series[-1] if series else None

    # Latest spatial graph (N-th Order Impact) for the domain. Cached for
    # 300s — see _get_cached_latest_spatial doc. None when no Pro report
    # for this domain has been generated yet; the frontend gracefully
    # falls back to whatever payload it was constructed with.
    latest_spatial = await _get_cached_latest_spatial(db, domain)

    return {
        "domain_id": domain,
        "days": int(days),
        "count": len(series),
        "warning_count": warning_count,
        "last_point": last,
        "series": series,
        "latest_spatial_contagion": latest_spatial,
    }
