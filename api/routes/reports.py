"""
api/routes/reports.py
Report endpoints: GET /api/reports, /api/reports/{id}
"""
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid
import logging
import traceback
from datetime import datetime, timezone

from db.models import Report
from db.database import get_db
from db.enums import ReportType
from api.auth import get_current_user_from_access, get_optional_current_user, resolve_optional_user
from api.gating import get_effective_tier, is_tier_sufficient, TIER_FREE

router = APIRouter(tags=["reports"])
logger = logging.getLogger(__name__)


@router.get("/reports/{report_id}")
async def get_report_detail(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[tuple] = Depends(get_optional_current_user)
):
    """Retrieve a specific report by ID (Strict Plan Gating for logged-in and guests)."""
    # current_user is AnalystProfile | None (Phase 35 Alignment)
    user = current_user
    user_role = user.user_role if user else "guest"
    stmt = select(Report).where(Report.id == report_id)
    report = (await db.execute(stmt)).scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    tier = await get_effective_tier(user)

    # ── Strict Plan Gating ────────────────────────────────────────────────
    plan_required = report.plan_required or "free"
    if not is_tier_sufficient(tier, plan_required) and user_role != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Subscription upgrade required. This report requires the '{plan_required}' plan."
        )

    def get_conf_score(level):
        return 0.92 if level == "High" else 0.65 if level == "Medium" else 0.35

    return {
        "id": str(report.id),
        "report_type": report.report_type,
        "topic_code": report.topic_code,
        "content_markdown": report.content_markdown,
        "title": report.title or f"{report.topic_code} Briefing",
        "teaser_md": report.teaser_md,
        "summary_bluf": report.teaser_md,
        "locked": False,
        "is_premium": report.is_premium,
        "source_count": report.source_count or 0,
        "confidence_level": str(report.confidence_level or "Low"),
        "confidence_score": get_conf_score(report.confidence_level),
        "created_at": report.created_at.isoformat() if hasattr(report.created_at, 'isoformat') else report.created_at,
        "plan_required": plan_required,
        "location_lat": report.location_lat,
        "location_lng": report.location_lng
    }


@router.get("/reports")
async def list_reports(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[tuple] = Depends(get_optional_current_user),
    limit: int = 10,
    topic: Optional[str] = None
):
    response.headers["X-API-Version"] = "2026-03-24-REBRAND-V1"
    user = resolve_optional_user(current_user)
    user_role = user.user_role if user else "guest"
    tier = await get_effective_tier(user)

    try:
        stmt = select(Report).where(
            (Report.report_type != ReportType.SYSTEM_DIAGNOSTIC.value) &
            (Report.report_type != "system") &
            (Report.topic_code != "system")
        )

        if topic:
            if topic.lower() == "global":
                # Match both "global" and NULL for the main briefing
                from sqlalchemy import or_
                stmt = stmt.where(or_(Report.topic_code == "global", Report.topic_code.is_(None)))
            else:
                stmt = stmt.where(Report.topic_code == topic)

        stmt = stmt.order_by(Report.created_at.desc()).limit(limit * 2)
        result = await db.execute(stmt)
        reports = result.scalars().all()

        filtered_reports = []
        seen_titles = set()
        for r in reports:
            # Deduplicate by Title (prevent exact duplicate briefings)
            if r.title and r.title in seen_titles:
                continue
            
            r_type = (r.report_type or "").lower()
            t_code = (r.topic_code or "").lower()
            r_plan = r.plan_required or "free"

            if "system" in r_type or "diagnostic" in r_type or t_code == "system":
                continue

            if not is_tier_sufficient(tier, r_plan) and user_role != "admin":
                continue

            filtered_reports.append(r)
            if r.title:
                seen_titles.add(r.title)

        final_reports = filtered_reports[:limit]

        return [
            {
                "id": str(r.id),
                "report_type": r.report_type or "unknown",
                "topic_code": r.topic_code or "global",
                "title": r.title or "Intelligence Briefing",
                "summary_bluf": r.teaser_md or "Summary analysis pending...",
                "is_premium": bool(r.is_premium),
                "plan_required": r.plan_required or "free",
                "confidence_score": 0.92 if r.confidence_level == "High" else 0.65 if r.confidence_level == "Medium" else 0.35,
                "created_at": r.created_at.isoformat() if hasattr(r.created_at, 'isoformat') else str(r.created_at),
                "location_lat": r.location_lat,
                "location_lng": r.location_lng
            } for r in final_reports
        ]
    except Exception as e:
        import os
        import traceback
        with open("tmp/api_error.log", "a") as f:
            f.write(f"\n--- ERROR at {datetime.now(timezone.utc)} ---\n")
            f.write(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# GET /public/reports/{report_id} was removed: it served up to 1000 characters of
# content_markdown for any report id with no auth dependency and no plan_required
# check. Every row in the table is plan_required 'pro' or 'experts'.
