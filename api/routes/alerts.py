"""
api/routes/alerts.py
Alert endpoints: GET /api/alerts, /api/alerts/live, POST /api/alerts/{id}/feedback
"""
from fastapi import APIRouter, Query, HTTPException, Depends
from sqlalchemy.future import select
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime, timezone
import uuid
import json
import logging

from db.models import AlertLog, AlertDelivery, AnalystProfile
from db.database import get_db
from api.gating import get_effective_tier, is_topic_allowed, _gate_cascading_impacts
from api.auth import blacklist_manager
from api.rate_limit import rate_limit

router = APIRouter(tags=["alerts"])
logger = logging.getLogger(__name__)


@router.get("/alerts")
async def get_alerts(
    severity: Optional[str] = None,
    suppressed: Optional[bool] = None,
    analyst_id: Optional[str] = None,
    topic: Optional[str] = None,
    limit: int = 20,
    since: Optional[datetime] = None,
    current_user: Optional[AnalystProfile] = Depends(rate_limit("/api/alerts")),
    db: AsyncSession = Depends(get_db)
):
    user = current_user
    tier = await get_effective_tier(user)

    # ── Topic gating ──────────────────────────────────────────────────────
    # ── Topic gating (Soft) ───────────────────────────────────────────────
    # We no longer block access with 403. Instead, the loop below will 
    # 'mask' the content if the topic isn't allowed for the user's tier.
    is_requested_topic_allowed = is_topic_allowed(tier, topic) if topic else True

    # Caching Logic
    cache_key = f"alerts:{severity}:{suppressed}:{analyst_id}:{topic}:{limit}:{since}"
    if await blacklist_manager._is_redis_available():
        try:
            cached = await blacklist_manager.redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except:
            pass

    # Base query
    stmt = select(AlertLog)

    if analyst_id:
        try:
            uid = uuid.UUID(analyst_id)
            stmt = stmt.join(AlertDelivery).where(AlertDelivery.analyst_id == uid)
        except ValueError:
            pass
    if severity:
        stmt = stmt.where(AlertLog.severity == severity)
    if suppressed is not None:
        stmt = stmt.where(AlertLog.suppressed == suppressed)
    if topic:
        stmt = stmt.where(AlertLog.topic == topic)
    if since:
        stmt = stmt.where(AlertLog.triggered_at >= since)

    stmt = stmt.order_by(AlertLog.triggered_at.desc()).limit(limit)
    result = await db.execute(stmt)
    alerts = result.scalars().all()

    formatted = [
        {
            "id": str(a.id),
            "target_label": a.target_label,
            "topic": a.topic,
            "trigger_type": a.trigger_type,
            "severity": a.severity,
            "triggered_at": a.triggered_at.isoformat(),
            "intensity": a.intensity,
            "feedback_score": a.feedback_score,
            "related_report_id": str(a.related_report_id) if a.related_report_id else None,
            "intelligence_score": a.intelligence_score,
            "fidelity_score": a.fidelity_score,
            "is_high_fidelity": a.is_high_fidelity,
            "status": a.status,
            "domain_count": a.metadata_json.get("domain_count", 0) if a.metadata_json else 0,
            "spike_delta": a.metadata_json.get("spike_delta", 0.0) if a.metadata_json else 0.0,
            "evidence_list": a.metadata_json.get("evidence_list", []) if a.metadata_json else [],
            "cascading_impacts": _gate_cascading_impacts(tier, a.metadata_json.get("cascading_impacts", [])) if a.metadata_json else [],
            "location_lat": a.location_lat,
            "location_lng": a.location_lng,
            "description": a.metadata_json.get("description") if a.metadata_json else None,
            "country": a.metadata_json.get("country") if a.metadata_json else None
        }
        for a in alerts
    ]

    # Post-process for Mosaic/Masking
    final_alerts = []
    for a in formatted:
        is_allowed = is_topic_allowed(tier, a["topic"])
        if is_allowed:
            a["is_locked"] = False
            final_alerts.append(a)
        else:
            # Mask sensitive forensic data
            a["is_locked"] = True
            a["target_label"] = "🔒 [RESTRICTED]"
            a["description"] = "Forensic intelligence for this event is restricted to Pro and Expert tiers. " \
                              "Upgrade to unlock full-spectrum risk data and email notifications."
            a["intensity"] = 0.0 # Clear intensity for locked
            a["cascading_impacts"] = [] # Clear impacts for locked
            final_alerts.append(a)

    # Store in Cache (60s TTL)
    if await blacklist_manager._is_redis_available():
        try:
            await blacklist_manager.redis_client.setex(cache_key, 60, json.dumps(final_alerts))
        except:
            pass

    return final_alerts


@router.get("/alerts/live")
async def get_live_alerts(
    limit: int = 15,
    current_user: Optional[AnalystProfile] = Depends(rate_limit("/api/alerts/live")),
    db: AsyncSession = Depends(get_db)
):
    """Provides a high-speed stream of high-fidelity signals for the dashboard pulse."""
    stmt = select(AlertLog).where(AlertLog.is_high_fidelity == True).order_by(AlertLog.triggered_at.desc()).limit(limit)
    result = await db.execute(stmt)
    alerts = result.scalars().all()

    user = current_user
    tier = await get_effective_tier(user)

    live_data = [
        {
            "id": str(a.id),
            "target_label": a.target_label,
            "topic": a.topic,
            "severity": a.severity,
            "triggered_at": a.triggered_at.isoformat(),
            "fidelity_score": a.fidelity_score,
            "intensity": a.intensity,
            "cascading_impacts": _gate_cascading_impacts(tier, a.metadata_json.get("cascading_impacts", [])) if a.metadata_json else [],
            "location_lat": a.location_lat,
            "location_lng": a.location_lng,
            "description": a.metadata_json.get("description") if a.metadata_json else None,
            "country": a.metadata_json.get("country") if a.metadata_json else None
        }
        for a in alerts
    ]
    
    # Applied Mosaic to live stream too
    final_live = []
    for a in live_data:
        is_allowed = is_topic_allowed(tier, a["topic"])
        if is_allowed:
            a["is_locked"] = False
        else:
            a["is_locked"] = True
            a["target_label"] = "🔒 [RESTRICTED]"
            a["description"] = "Detailed tactical signal is restricted."
            a["cascading_impacts"] = []
        final_live.append(a)

    return final_live


@router.get("/alerts/{alert_id}")
async def get_alert(
    alert_id: uuid.UUID,
    current_user: Optional[AnalystProfile] = Depends(rate_limit("/api/alerts/{id}")),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(AlertLog).where(AlertLog.id == alert_id)
    result = await db.execute(stmt)
    a = result.scalar_one_or_none()
    
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")

    tier = await get_effective_tier(current_user)
    is_allowed = is_topic_allowed(tier, a.topic)

    data = {
        "id": str(a.id),
        "target_label": a.target_label if is_allowed else "🔒 [RESTRICTED]",
        "topic": a.topic,
        "trigger_type": a.trigger_type,
        "severity": a.severity,
        "triggered_at": a.triggered_at.isoformat(),
        "intensity": a.intensity if is_allowed else 0.0,
        "feedback_score": a.feedback_score,
        "related_report_id": str(a.related_report_id) if a.related_report_id else None,
        "intelligence_score": a.intelligence_score,
        "fidelity_score": a.fidelity_score,
        "status": a.status,
        "cascading_impacts": _gate_cascading_impacts(tier, a.metadata_json.get("cascading_impacts", [])) if (a.metadata_json and is_allowed) else [],
        "location_lat": a.location_lat,
        "location_lng": a.location_lng,
        "description": (a.metadata_json.get("description") if a.metadata_json else None) if is_allowed else "Forensic intelligence restricted.",
        "country": a.metadata_json.get("country") if a.metadata_json else None,
        "is_locked": not is_allowed
    }

    return data


@router.post("/alerts/{alert_id}/feedback")
async def submit_feedback(
    alert_id: uuid.UUID,
    data: dict,
    current_user: tuple = Depends(rate_limit()),
    db: AsyncSession = Depends(get_db)
):
    score = data.get("score")
    if not score or not (1 <= score <= 5):
        raise HTTPException(status_code=400, detail="Score must be 1-5")

    stmt = select(AlertLog).where(AlertLog.id == alert_id)
    alert = (await db.execute(stmt)).scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.feedback_score = score
    await db.commit()
    return {"status": "success"}
