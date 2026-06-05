"""
api/routes/alerts.py
Alert endpoints: GET /api/alerts, /api/alerts/live, POST /api/alerts/{id}/feedback
"""
import asyncio
import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, HTTPException, Depends, BackgroundTasks
from sqlalchemy.future import select
from sqlalchemy import desc, case, Float
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AlertLog, AlertDelivery, AnalystProfile
from db.database import get_db, AsyncSessionLocal
from processor.impact_discovery import ImpactDiscoveryEngine
from api.gating import get_effective_tier, is_topic_allowed, _gate_cascading_impacts, is_tier_sufficient, PlanTier, gate_alert_payload
from api.auth import blacklist_manager
from api.rate_limit import rate_limit
from analysis.intensity_pressure import PERCENT_STREAM_FLOOR


def _above_stream_floor(a: dict) -> bool:
    """Data-Maturity Guardrail: the live Alert Stream features ONLY matured,
    computed telemetry. An alert is shown strictly when its intensity_pct is a
    real number >= PERCENT_STREAM_FLOOR (15%). Anything null / 0 / uncomputed
    (cold-start with no reliable baseline) is dropped from the feed view — the
    raw row still persists for the worker to build baselines from over time."""
    pct = a.get("intensity_pct")
    return isinstance(pct, (int, float)) and pct >= PERCENT_STREAM_FLOOR

router = APIRouter(tags=["alerts"])
logger = logging.getLogger(__name__)


# PUBLIC ENDPOINT — the Alert Stream is open to everyone. Auth is OPTIONAL via
# `get_optional_current_user` (resolved through rate_limit): a missing OR invalid
# token yields current_user=None (guest/free tier) and a normal 200 with the
# calibrated, PERCENT_STREAM_FLOOR-filtered public rows — never a 401/403. Do not
# add a mandatory-auth dependency here.
@router.get("/alerts")
async def get_alerts(
    severity: Optional[str] = None,
    suppressed: Optional[bool] = None,
    analyst_id: Optional[str] = None,
    topic: Optional[str] = None,
    limit: int = 30,
    since: Optional[datetime] = None,
    current_user: Optional[AnalystProfile] = Depends(rate_limit("/api/alerts")),
    db: AsyncSession = Depends(get_db)
):
    try:
        return await _get_alerts_impl(
            severity=severity,
            suppressed=suppressed,
            analyst_id=analyst_id,
            topic=topic,
            limit=limit,
            since=since,
            current_user=current_user,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Alert fetch failed (get_alerts): %s", e, exc_info=True)
        return []


async def _get_alerts_impl(
    *,
    severity: Optional[str],
    suppressed: Optional[bool],
    analyst_id: Optional[str],
    topic: Optional[str],
    limit: int,
    since: Optional[datetime],
    current_user: Optional[AnalystProfile],
    db: AsyncSession,
) -> list:
    user = current_user
    tier = await get_effective_tier(user)

    # ── Topic gating ──────────────────────────────────────────────────────
    # ── Topic gating (Soft) ───────────────────────────────────────────────
    # We no longer block access with 403. Instead, the loop below will 
    # 'mask' the content if the topic isn't allowed for the user's tier.
    is_requested_topic_allowed = is_topic_allowed(tier, topic) if topic else True

    # Caching Logic
    cache_key = f"alerts:{tier}:{severity}:{suppressed}:{analyst_id}:{topic}:{limit}:{since}"
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
    else:
        # Active feed EXCLUDES suppressed/merged rows by default (clustered
        # duplicates are set suppressed=True). Without this the stream re-shows
        # every collapsed duplicate — the dedup is invisible to the UI.
        stmt = stmt.where(AlertLog.suppressed == False)  # noqa: E712
    if topic:
        from processor.topic_registry import (
            INTERNAL_TO_STRATEGIC,
            STRATEGIC_TO_INTERNAL,
            normalize_canonical_topic,
        )

        canonical = normalize_canonical_topic(topic)
        topic_keys = {canonical, topic.strip()}
        legacy = STRATEGIC_TO_INTERNAL.get(canonical)
        if legacy:
            topic_keys.add(legacy)
        for k, v in INTERNAL_TO_STRATEGIC.items():
            if v == canonical:
                topic_keys.add(k)
                topic_keys.add(k.upper())
        stmt = stmt.where(AlertLog.topic.in_(topic_keys))
    if since:
        stmt = stmt.where(AlertLog.triggered_at >= since)

    # Data-Maturity floor: on the DEFAULT (all-topics) stream, drop sub-15% noise
    # so the limited window holds the calibrated signals. BUT when the user
    # explicitly drills into a topic/domain tab (e.g. Energy), BYPASS the floor and
    # fall back to severity+recency ordering — a busy domain whose per-domain
    # percentile model scores most alerts < 15% must not be rendered completely
    # invisible. Suppressed rows are still excluded; ordering keeps the strongest
    # signals first.
    if not topic:
        stmt = stmt.where(
            AlertLog.metadata_json["intensity_pct"].astext.cast(Float) >= PERCENT_STREAM_FLOOR
        )

    # Order by THREAT PRIORITY then recency so the rare CRITICAL/ELEVATED signals
    # always make the limited window (they'd otherwise be squeezed out by the
    # high volume of recent WATCH-tier telemetry). The client re-sorts identically.
    _sev_rank = case(
        (AlertLog.severity == "critical", 3),
        (AlertLog.severity == "elevated", 2),
        (AlertLog.severity == "watch", 1),
        else_=0,
    )
    stmt = stmt.order_by(_sev_rank.desc(), AlertLog.triggered_at.desc()).limit(limit)
    result = await db.execute(stmt)
    alerts = result.scalars().all()

    formatted = [
        {
            "id": str(a.id),
            "target_label": a.target_label,
            "title": (
                (a.metadata_json or {}).get("display_title")
                or a.target_label
            ),
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
            "country": a.metadata_json.get("country") if a.metadata_json else None,
            "source_url": next((e.get("url") or e.get("link") for e in a.metadata_json.get("evidence_list", []) if e.get("url") or e.get("link")), None) if a.metadata_json else None,
            "is_partial": False,
            "intensity_label": "High" if a.intensity >= 8.0 else "Elevated" if a.intensity >= 4.0 else "Low",
            "intensity_display": f"{a.intensity:.1f}",
            "intensity_pct": a.metadata_json.get("intensity_pct") if isinstance(a.metadata_json, dict) else None,
            "backbone_discovery_status": a.metadata_json.get("backbone_discovery_status", "idle") if a.metadata_json else "idle"
        }
        for a in alerts
    ]

    # Payload tiering: $19 Basic gets evidence truncated to 3 + AI brief stripped;
    # $99 Institutional ( >= EXPERTS) gets the full payload. DEV_MODE (default OFF)
    # only elevates every caller to full during a deliberate audit pass; in
    # production this actively shapes Free/Basic payloads. Feed cards stay
    # clickable (is_locked False) — content is withheld via the payload, not a
    # card-level lock overlay.
    final_alerts = []
    for a in formatted:
        a["is_locked"] = False
        final_alerts.append(gate_alert_payload(a, tier))

    # Ground-floor: drop sub-baseline (<25%) noise from the active stream view.
    final_alerts = [a for a in final_alerts if _above_stream_floor(a)]

    # Store in Cache (60s TTL)
    if await blacklist_manager._is_redis_available():
        try:
            await blacklist_manager.redis_client.setex(cache_key, 60, json.dumps(final_alerts))
        except:
            pass

    return final_alerts


# PUBLIC ENDPOINT — same open contract as GET /alerts: optional auth, guests
# (no/invalid token) get a normal 200 of public pulse rows, never a 401/403.
@router.get("/alerts/live")
async def get_live_alerts(
    limit: int = 30,
    current_user: Optional[AnalystProfile] = Depends(rate_limit("/api/alerts/live")),
    db: AsyncSession = Depends(get_db)
):
    """Provides a high-speed stream of high-fidelity signals for the dashboard pulse."""
    try:
        return await _get_live_alerts_impl(limit, current_user, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Alert fetch failed (get_live_alerts): %s", e, exc_info=True)
        return []


async def _get_live_alerts_impl(
    limit: int,
    current_user: Optional[AnalystProfile],
    db: AsyncSession,
) -> list:
    stmt = select(AlertLog).where(AlertLog.is_high_fidelity == True, AlertLog.suppressed == False).order_by(AlertLog.triggered_at.desc()).limit(limit)  # noqa: E712
    result = await db.execute(stmt)
    alerts = result.scalars().all()

    user = current_user
    tier = await get_effective_tier(user)

    live_data = [
        {
            "id": str(a.id),
            "target_label": a.target_label,
            "title": (
                (a.metadata_json or {}).get("display_title")
                or a.target_label
            ),
            "topic": a.topic,
            "severity": a.severity,
            "triggered_at": a.triggered_at.isoformat(),
            "fidelity_score": a.fidelity_score,
            "intensity": a.intensity,
            "cascading_impacts": _gate_cascading_impacts(tier, a.metadata_json.get("cascading_impacts", [])) if a.metadata_json else [],
            "location_lat": a.location_lat,
            "location_lng": a.location_lng,
            "description": a.metadata_json.get("description") if a.metadata_json else None,
            "country": a.metadata_json.get("country") if a.metadata_json else None,
            "source_url": next((e.get("url") or e.get("link") for e in a.metadata_json.get("evidence_list", []) if e.get("url") or e.get("link")), None) if a.metadata_json else None,
            "is_partial": False,
            "intensity_label": "High" if a.intensity >= 8.0 else "Elevated" if a.intensity >= 4.0 else "Low",
            "intensity_display": f"{a.intensity:.1f}",
            "intensity_pct": a.metadata_json.get("intensity_pct") if isinstance(a.metadata_json, dict) else None,
            "backbone_discovery_status": a.metadata_json.get("backbone_discovery_status", "idle") if a.metadata_json else "idle",
            "evidence_list": a.metadata_json.get("evidence_list", []) if a.metadata_json else [],
        }
        for a in alerts
    ]
    
    # Fully-unlocked mode: no masking on the live stream either.
    final_live = []
    for a in live_data:
        a["is_locked"] = False
        a["is_partial"] = False
        final_live.append(a)

    # Ground-floor: drop sub-baseline (<25%) noise from the active stream view.
    final_live = [a for a in final_live if _above_stream_floor(a)]

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
    is_at_least_pro = is_tier_sufficient(tier, PlanTier.PRO.value)
    is_topic_locked = not is_topic_allowed(tier, a.topic)

    data = {
        "id": str(a.id),
        "target_label": a.target_label,
        "title": (
            (a.metadata_json or {}).get("display_title")
            or a.target_label
        ),
        "topic": a.topic,
        "trigger_type": a.trigger_type,
        "severity": a.severity,
        "triggered_at": a.triggered_at.isoformat(),
        "intensity": a.intensity,
        "feedback_score": a.feedback_score,
        "related_report_id": str(a.related_report_id) if a.related_report_id else None,
        "intelligence_score": a.intelligence_score,
        "fidelity_score": a.fidelity_score,
        "status": a.status,
        "cascading_impacts": _gate_cascading_impacts(tier, a.metadata_json.get("cascading_impacts", [])) if (a.metadata_json) else [],
        "location_lat": a.location_lat,
        "location_lng": a.location_lng,
        "is_locked": is_topic_locked,
        "is_partial": False,
        "intensity_label": "High" if a.intensity >= 8.0 else "Elevated" if a.intensity >= 4.0 else "Low",
        "intensity_display": f"{a.intensity:.1f}",
        "intensity_pct": a.metadata_json.get("intensity_pct") if isinstance(a.metadata_json, dict) else None,
        "backbone_discovery_status": a.metadata_json.get("backbone_discovery_status", "idle") if a.metadata_json else "idle",
        "source_url": next((e.get("url") or e.get("link") for e in a.metadata_json.get("evidence_list", []) if e.get("url") or e.get("link")), None) if a.metadata_json else None,
        "evidence_list": a.metadata_json.get("evidence_list", []) if a.metadata_json else [],
    }

    # Payload tiering ($19 Basic vs $99 Institutional). DEV_MODE (default OFF)
    # elevates to full only during audit passes; content withheld via payload,
    # not a card-level lock (is_locked stays False).
    data["is_locked"] = False
    data = gate_alert_payload(data, tier)

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

async def run_background_discovery(alert_id: uuid.UUID, title: str, summary: str):
    """Internal worker to execute LLM analysis out-of-band."""
    async with AsyncSessionLocal() as session:
        try:
            from processor.impact_discovery import ImpactDiscoveryEngine
            engine = ImpactDiscoveryEngine(session)
            logging.getLogger(__name__).info(f"[Antigravity] Spawning Background Discovery Engine for Alert: {alert_id}")
            # Use specific alert_id to enable internal persistence
            await engine.run_discovery(
                trigger_item_id=uuid.uuid4(),
                title=title,
                summary=summary,
                alert_id=alert_id
            )
            logging.getLogger(__name__).info(f"[Antigravity] Background Discovery Engine SUCCESS for Alert: {alert_id}")
        except Exception as e:
            logging.getLogger(__name__).error(f"[Antigravity] Background analysis failed for {alert_id}: {e}")
            # Mark as failed in DB
            stmt = select(AlertLog).where(AlertLog.id == alert_id)
            res = await session.execute(stmt)
            alert = res.scalar_one_or_none()
            if alert:
                meta = dict(alert.metadata_json) if alert.metadata_json else {}
                meta["backbone_discovery_status"] = "failed"
                alert.metadata_json = meta
                await session.commit()

@router.post("/alerts/{alert_id}/analyze")
async def upgrade_to_ai_analysis(
    alert_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: Optional[AnalystProfile] = Depends(rate_limit("/api/alerts/analyze")),
    db: AsyncSession = Depends(get_db)
):
    """Triggers real-time AI impact discovery for an alert (Asynchronous Background Job)."""
    stmt = select(AlertLog).where(AlertLog.id == alert_id)
    alert = (await db.execute(stmt)).scalar_one_or_none()
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    # [v10.29] Efficiency Check: Only run if not already processing or complete
    meta = dict(alert.metadata_json) if alert.metadata_json else {}
    status = meta.get("backbone_discovery_status", "idle")
    existing_impacts = meta.get("cascading_impacts", [])

    if any(i.get("source") == "ai_reasoning" for i in existing_impacts) or status == "complete":
        return {"status": "success", "message": "Retrieving cached deep analysis", "cascading_impacts": existing_impacts}

    if status == "processing":
        # [v10.30] Stale analysis check: if stuck in processing for > 5 mins, allow manual retry
        last_ts_str = meta.get("backbone_discovery_ts")
        if last_ts_str:
            try:
                last_ts = datetime.fromisoformat(last_ts_str)
                if last_ts.tzinfo is None: last_ts = last_ts.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - last_ts < timedelta(minutes=5):
                    return {"status": "processing", "message": "Analysis is already in progress"}
                else:
                    logger.warning(f"[Antigravity] Alert {alert_id} analysis STALE — Restarting.")
            except:
                pass # Default to blocking if parse fails
        else:
            return {"status": "processing", "message": "Analysis is already in progress"}

    # Set status to processing and trigger background task
    meta["backbone_discovery_status"] = "processing"
    meta["backbone_discovery_ts"] = datetime.now(timezone.utc).isoformat()
    alert.metadata_json = meta
    await db.commit()

    summary = (meta.get("description") if meta else None) or f"Triggered on {alert.topic}"
    background_tasks.add_task(run_background_discovery, alert.id, alert.target_label, summary)

    return {
        "status": "processing",
        "message": "AI backbone discovery initiated in background"
    }
