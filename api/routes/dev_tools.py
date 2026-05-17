"""
Local development utilities. Disabled unless ALLOW_DEV_TIER_OVERRIDE=true and ENV != production.
"""

import os
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, func, select

from db.database import AsyncSessionLocal
from db.models import AlertLog, Report
from jobs.pro_report_generator import run_pro_structural_report_generation

router = APIRouter(prefix="/dev", tags=["Dev Tools"])

DEFAULT_DOMAINS = [
    "energy_resource_risk",
    "global_market_intelligence",
    "ai_semiconductor_intelligence",
    "supply_chain_intelligence",
    "crypto_geopolitics",
    "defense_technology",
]


def _dev_tools_allowed() -> bool:
    env_name = os.environ.get("ENV", "development").lower()
    allow = os.environ.get("ALLOW_DEV_TIER_OVERRIDE", "false").lower() == "true"
    return env_name != "production" and allow


@router.post("/generate-pro-structural-briefs")
@router.get("/generate-pro-structural-briefs")
async def generate_pro_structural_briefs() -> Dict[str, Any]:
    """
    Manually generate Pro Structural Briefs for all core domains (local dev only).
    """
    if not _dev_tools_allowed():
        raise HTTPException(
            status_code=403,
            detail="Dev tools disabled. Set ALLOW_DEV_TIER_OVERRIDE=true and ENV!=production.",
        )

    async with AsyncSessionLocal() as db:
        before = (
            await db.execute(
                select(func.count(Report.id)).where(Report.report_type == "pro_structural")
            )
        ).scalar() or 0

    generated: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for domain_id in DEFAULT_DOMAINS:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(AlertLog)
                .where(AlertLog.topic == domain_id, AlertLog.suppressed == False)
                .order_by(desc(AlertLog.triggered_at))
                .limit(1)
            )
            alert = (await db.execute(stmt)).scalar_one_or_none()

        alert_id = str(alert.id) if alert else None
        try:
            report = await run_pro_structural_report_generation(
                alert_id=alert_id,
                domain_id=domain_id,
            )
            generated.append(
                {
                    "domain_id": domain_id,
                    "alert_id": alert_id,
                    "report_id": str(report.id),
                    "title": report.title,
                    "topic_code": report.topic_code,
                    "content_chars": len(report.content_markdown or ""),
                }
            )
        except Exception as exc:
            errors.append({"domain_id": domain_id, "alert_id": alert_id, "error": str(exc)})

    async with AsyncSessionLocal() as db:
        after = (
            await db.execute(
                select(func.count(Report.id)).where(Report.report_type == "pro_structural")
            )
        ).scalar() or 0

    return {
        "status": "ok",
        "pro_structural_before": before,
        "pro_structural_after": after,
        "delta": after - before,
        "generated": generated,
        "errors": errors,
    }
