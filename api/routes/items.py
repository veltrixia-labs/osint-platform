"""
api/routes/items.py
Public item feed: GET /api/items?topic=<code>&limit=N

Returns raw collected items for a single strategic category, newest-first.
Backs the per-domain tab's second section ("full sector feed" — the
comprehensive list). It is intentionally:
  - LLM-free / compute-free: a plain time-ordered window over Item rows. No
    importance, no anomaly, no clustering, no lightweight_score (handover 15.5).
  - ungated: clustering/importance are themselves free-tier; only downstream
    company/market/supply-chain impact analysis is Pro+. So no tier gating and no
    payload masking - everyone (guests included) gets the full list.
  - additive: does not touch /alerts, alert_logs, signal_job, or clustering.
"""
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, Depends
from sqlalchemy import func
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Item
from db.database import get_db
from processor.topic_registry import internal_topic_for_fallback

router = APIRouter(tags=["items"])
logger = logging.getLogger(__name__)

# limit bounds - comprehensive-but-finite. Newest-100 is a few days for the busiest
# categories; max 300 lets a power user pull deeper. Tune here if needed.
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 300


# ★ The feed is ordered by WHEN THE NEWS WAS PUBLISHED, not when we ingested it (2026-10-07).
#   Ordering by created_at put every late arrival at the top as "newest": a story ingested a
#   day late sat above the day's news, and on 2026-10-07 re-ingested January videos were shown
#   as today's (vault audit §12.66-§12.67). Measured over 7 days before the change: 0.6% of
#   row positions move >10 places, all of them late arrivals (lag 1.8-25.7h).
#   ORDERED_AT is published_at, falling back to created_at when published_at is NULL, and never
#   later than created_at (a future-dated entry cannot pin itself to the top). The API returns
#   this exact value as `ordered_at`, and the client displays and groups by it, so what the
#   list is sorted by and what it shows cannot drift apart.
ORDERED_AT = func.least(func.coalesce(Item.published_at, Item.created_at), Item.created_at)


def _serialize_item(it: Item, ordered_at=None) -> Dict[str, Any]:
    """Time-ordered list payload. Deliberately omits importance / anomaly /
    lightweight_score / cluster_id (handover 15.5): this is a comprehensive raw
    feed, not a scored selection. title_original/lang are included so a future
    multilingual list can render the native headline."""
    return {
        "id": str(it.id),
        "title": it.title,
        "title_original": it.title_original,
        "lang": it.lang,
        "source_name": it.source_name,
        "source_url": it.source_url,
        "published_at": it.published_at.isoformat() if it.published_at else None,
        "created_at": it.created_at.isoformat() if it.created_at else None,
        # The value this list is ordered by (see ORDERED_AT). Display and group by THIS field.
        "ordered_at": ordered_at.isoformat() if ordered_at else None,
        "reliability_weight": it.reliability_weight,
        "category": it.category,
    }


# PUBLIC ENDPOINT - open to everyone (guests included), mirroring the open contract
# of GET /alerts. No mandatory-auth dependency, no tier gating, no masking.
@router.get("/items")
async def get_items(
    topic: Optional[str] = Query(
        None,
        description="Strategic topic code. Accepts UI UPPER code (AI_TECH), legacy "
                    "snake_case (ai_semiconductor_intelligence), or known aliases.",
    ),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    # No topic -> empty list (the "All" tab does not use this endpoint).
    if not topic:
        return []

    # Resolve any accepted spelling to the snake_case Item.category value.
    # internal_topic_for_fallback('AI_TECH') -> 'ai_semiconductor_intelligence'.
    # Defensive: unknown input must yield an empty result, never a 500.
    try:
        category = internal_topic_for_fallback(topic)
    except Exception:
        category = None
    if not category:
        return []

    ordered_at = ORDERED_AT.label("ordered_at")
    stmt = (
        select(Item, ordered_at)
        .where(Item.category == category)
        .order_by(ordered_at.desc().nullslast(), Item.id)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [_serialize_item(it, oa) for it, oa in result.all()]
