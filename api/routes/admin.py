"""
Admin-only endpoints (tier override for production QA without Stripe charges).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user_from_access
from api.gating import get_effective_tier, is_admin_profile
from db.database import get_db
from db.enums import PlanTier
from db.models import AnalystProfile

router = APIRouter(prefix="/admin", tags=["admin"])

ALLOWED_MANUAL_TIERS = {
    PlanTier.FREE.value,
    PlanTier.PRO.value,
    PlanTier.EXPERTS.value,
    PlanTier.ENTERPRISE.value,
}


class ToggleTierRequest(BaseModel):
    tier: Optional[str] = Field(
        default=None,
        description="pro, experts, free, enterprise; omit or null to clear override",
    )


@router.post("/toggle-tier")
async def toggle_tier(
    body: ToggleTierRequest,
    current_user_data: tuple = Depends(get_current_user_from_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Set or clear the caller's manual_tier (admin only).
    When manual_tier is set, Stripe subscription state is ignored for effective tier.
    """
    user: AnalystProfile = current_user_data[0]
    if not is_admin_profile(user):
        raise HTTPException(status_code=403, detail="Admin access required")

    raw = body.tier
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        user.manual_tier = None
    else:
        tier = raw.strip().lower()
        if tier not in ALLOWED_MANUAL_TIERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tier. Allowed: {sorted(ALLOWED_MANUAL_TIERS)} or clear.",
            )
        user.manual_tier = tier

    await db.commit()
    await db.refresh(user)
    effective = await get_effective_tier(user)
    return {
        "status": "ok",
        "manual_tier": user.manual_tier,
        "tier": effective,
    }
