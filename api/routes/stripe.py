"""
Stripe checkout and webhook endpoints (/api/stripe/*).
"""
import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user_from_access
from api.rate_limit import rate_limit
from api.stripe_service import create_checkout_session_for_user, process_stripe_webhook_event
from config.settings import settings
from db.database import get_db
from db.models import AnalystProfile

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stripe"])


class CreateCheckoutRequest(BaseModel):
    tier: str = Field(..., description="pro or experts")


@router.post("/create-checkout")
async def create_checkout(
    body: CreateCheckoutRequest,
    current_user: tuple = Depends(get_current_user_from_access),
    _rt: tuple = Depends(rate_limit("/api/stripe/create-checkout")),
    db: AsyncSession = Depends(get_db),
):
    """Create Stripe Checkout session; client_reference_id = logged-in user.id."""
    user: AnalystProfile = current_user[0]
    try:
        session = create_checkout_session_for_user(user, body.tier)
        return {"url": session.url, "session_id": session.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Stripe create-checkout failed: %s", e)
        raise HTTPException(status_code=500, detail="Checkout creation failed") from e


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Stripe webhook (checkout.session.completed, customer.subscription.deleted, etc.)."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except Exception as e:
        logger.warning("Webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature") from e

    return await process_stripe_webhook_event(db, event)
