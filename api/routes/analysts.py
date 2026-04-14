"""
api/routes/analysts.py
Analyst endpoints: GET /api/analysts, POST /api/analysts/{id}/watchlist
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import logging

from db.models import AnalystProfile
from db.database import get_db
from api.auth import get_current_user_from_access
from db.enums import PlanTier
from api.gating import (
    get_effective_tier, get_watchlist_limit, can_add_watchlist_keywords,
    requires_tier, TIER_FREE
)
from api.rate_limit import rate_limit
from fastapi import APIRouter
import logging

router = APIRouter(tags=["analysts"])
logger = logging.getLogger(__name__)

@router.get("/analysts")
async def get_analysts(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[AnalystProfile] = Depends(requires_tier(PlanTier.FREE.value))
):
    stmt = select(AnalystProfile).where(AnalystProfile.is_active == True)
    analysts = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(a.id),
            "chat_id": a.telegram_chat_id,
            "watch_keywords": a.watch_keywords,
            "watch_entities": a.watch_entities,
            "watch_sectors": a.watch_sectors
        } for a in analysts
    ]


@router.post("/analysts/{analyst_id}/watchlist")
async def update_watchlist(
    analyst_id: uuid.UUID,
    data: dict,
    current_user: tuple = Depends(rate_limit()),
    db: AsyncSession = Depends(get_db)
):
    user = current_user  # rate_limit() returns AnalystProfile directly
    if user.id != analyst_id and user.user_role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to update this watchlist")

    stmt = select(AnalystProfile).where(AnalystProfile.id == analyst_id)
    analyst = (await db.execute(stmt)).scalar_one_or_none()
    if not analyst:
        raise HTTPException(status_code=404, detail="Analyst not found")

    # ── Watchlist keyword limit enforcement ───────────────────────────────
    tier = await get_effective_tier(analyst)
    if "keywords" in data:
        new_total = len(data["keywords"]) if isinstance(data["keywords"], list) else 0
        kw_limit = get_watchlist_limit(tier)
        if not can_add_watchlist_keywords(tier, new_total):
            raise HTTPException(
                status_code=403,
                detail=f"Watchlist keyword limit reached. "
                       f"Your plan ({tier}) allows {kw_limit} keywords, "
                       f"but the update would result in {new_total}. "
                       f"Upgrade your plan to add more."
            )

    if "keywords" in data: analyst.watch_keywords = data["keywords"]
    if "entities" in data: analyst.watch_entities = data["entities"]
    if "sectors" in data: analyst.watch_sectors = data["sectors"]

    await db.commit()
    return {"status": "success"}
