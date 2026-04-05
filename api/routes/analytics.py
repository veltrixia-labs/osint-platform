"""
api/routes/analytics.py
Analytics endpoints: POST /api/analytics/event
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
import uuid
import logging

from db.models import AnalystProfile, AnalyticsEvent
from db.database import get_db
from api.auth import get_optional_current_user

router = APIRouter(tags=["analytics"])
logger = logging.getLogger(__name__)


class AnalyticsEventCreate(BaseModel):
    event_type: str
    report_id: Optional[uuid.UUID] = None
    metadata_json: Optional[dict] = None


@router.post("/analytics/event")
async def log_analytics_event(
    event: AnalyticsEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[AnalystProfile] = Depends(get_optional_current_user)
):
    """Log an analytics event (preview_view, cta_click, full_view, etc.)"""
    allowed_unauth = ["preview_view", "cta_click", "checkout_flow"]
    if not current_user and event.event_type not in allowed_unauth:
        raise HTTPException(status_code=403, detail="Unauthenticated users can only log preview and CTA events")

    user_obj = None
    if current_user:
        if isinstance(current_user, tuple):
            user_obj = current_user[0]
        else:
            user_obj = current_user

    new_event = AnalyticsEvent(
        event_type=event.event_type,
        report_id=event.report_id,
        user_id=user_obj.id if user_obj else None,
        metadata_json=event.metadata_json
    )
    db.add(new_event)
    await db.commit()
    return {"status": "ok", "event_id": str(new_event.id)}
