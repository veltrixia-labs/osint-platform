"""
API Routes for Pro Structural Briefs.

Provides endpoints for Pro and Expert users to access advanced 
structural impact reports.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from typing import Any, Optional
import uuid

from db.database import AsyncSessionLocal
from db.models import Report, AnalystProfile, AlertLog
from api.gating import get_effective_tier, TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE, TIER_GUEST
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
    """Pro Brief detail requires a logged-in user with Pro tier or above."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = current_user[0] if isinstance(current_user, tuple) else current_user
    tier = await get_effective_tier(user)
    allowed = [TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE]
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
    allowed_tiers = [TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE]
    try:
        report_uuid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report ID format.")

    stmt = select(Report).where(Report.id == report_uuid)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
        
    # Double check gating on the specific report
    if report.plan_required == "pro" and tier not in allowed_tiers:
         raise HTTPException(status_code=403, detail="Insufficient tier for this report.")
        
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
