"""
api/routes/free_feed.py
Free Alert Feed endpoints: GET /api/free/alerts, /api/free/alerts/{id}
"""
import uuid
import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Query, HTTPException, Depends
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import cast, String, or_

from db.models import AlertLog, AnalystProfile
from db.database import get_db
from api.rate_limit import rate_limit

router = APIRouter(tags=["free_feed"])
logger = logging.getLogger(__name__)


def _alertlog_has_free_alert_clause():
    """
    Match rows that carry a persisted free_alert payload.
    JSON path + text fallback: some drivers/serializations differ from a plain
    substring search on cast-to-text alone.
    """
    key = AlertLog.metadata_json["free_alert"]
    text_blob = cast(AlertLog.metadata_json, String)
    return or_(key.is_not(None), text_blob.contains('"free_alert"'))


def _extract_free_alert(alert_log: AlertLog) -> Optional[dict]:
    """
    Extracts the free_alert payload from an AlertLog's metadata_json.
    Returns None if the field is absent or malformed.
    """
    meta = alert_log.metadata_json
    if not isinstance(meta, dict):
        return None
    free_alert = meta.get("free_alert")
    if not isinstance(free_alert, dict):
        return None
    return free_alert


def _serialize(alert_log: AlertLog, free_alert: dict, subscription_tier: Optional[str] = None) -> dict:
    """Builds the public-facing response dict from an AlertLog + free_alert payload."""
    tier = (subscription_tier or "free").lower()
    paid_tier = tier in ("pro", "enterprise", "experts")

    raw_impacts = free_alert.get("company_impacts") or []
    display_cap = int(free_alert.get("free_company_impact_display_cap") or 6)

    if paid_tier:
        company_impacts_out = raw_impacts
        additional_pro_count = 0
    else:
        company_impacts_out = raw_impacts[:display_cap] if display_cap > 0 else raw_impacts
        additional_pro_count = int(free_alert.get("additional_pro_count") or 0)

    return {
        "alert_id":             free_alert.get("alert_id", str(alert_log.id)),
        "title":                free_alert.get("title", alert_log.target_label or ""),
        "topic":                free_alert.get("topic", alert_log.topic or ""),
        "target_label":         free_alert.get("target_label", alert_log.target_label or ""),
        "triggered_at":         free_alert.get(
                                    "triggered_at",
                                    alert_log.triggered_at.isoformat() if alert_log.triggered_at else ""
                                ),
        "related_news_count":   free_alert.get("related_news_count", 0),
        "related_news_source":  free_alert.get("related_news_source", "unknown"),
        "related_entities_count": free_alert.get("related_entities_count", 0),
        "related_news":         free_alert.get("related_news", []),
        "content_markdown":     free_alert.get("content_markdown", ""),
        "generated_at":         free_alert.get("generated_at", ""),
        "location_context":     free_alert.get("location_context"),
        "company_impacts":      company_impacts_out,
        "sector_impacts":       free_alert.get("sector_impacts") or [],
        "additional_pro_count": additional_pro_count,
    }


@router.get("/free/alerts")
async def list_free_alerts(
    topic:   Optional[str] = Query(None, description="Filter by topic code"),
    limit:   int           = Query(40, ge=1, le=100),
    current_user: Optional[AnalystProfile] = Depends(rate_limit("/api/free/alerts")),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns Free Alert Feed items for authenticated Free+ users.
    Only AlertLogs that have a persisted metadata_json.free_alert are returned.
    No LLM, forecast, or scenario logic is invoked.
    """
    stmt = (
        select(AlertLog)
        .where(_alertlog_has_free_alert_clause())
        .order_by(AlertLog.triggered_at.desc())
        .limit(limit * 3)          # over-fetch to allow Python-side dedup / topic filter
    )

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

    result = await db.execute(stmt)
    rows = result.scalars().all()

    tier = "free"
    if current_user is not None:
        tier = getattr(current_user, "subscription_tier", None) or "free"

    output = []
    for row in rows:
        fa = _extract_free_alert(row)
        if fa is None:
            continue
        output.append(_serialize(row, fa, tier))
        if len(output) >= limit:
            break

    if rows and not output:
        logger.warning(
            "list_free_alerts: %s DB rows matched free_alert filter but none serialized "
            "(check metadata_json.free_alert shape / topic=%r)",
            len(rows),
            topic,
        )

    return output


@router.get("/free/alerts/{alert_id}")
async def get_free_alert(
    alert_id: uuid.UUID,
    current_user: Optional[AnalystProfile] = Depends(rate_limit("/api/free/alerts/{id}")),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a single Free Alert Feed item by AlertLog ID.
    Raises 404 if the alert does not exist or has no free_alert payload.
    """
    stmt = select(AlertLog).where(AlertLog.id == alert_id)
    row = (await db.execute(stmt)).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")

    fa = _extract_free_alert(row)
    if fa is None:
        raise HTTPException(
            status_code=404,
            detail="Free Alert Feed data not yet generated for this alert"
        )

    tier = "free"
    if current_user is not None:
        tier = getattr(current_user, "subscription_tier", None) or "free"

    return _serialize(row, fa, tier)
