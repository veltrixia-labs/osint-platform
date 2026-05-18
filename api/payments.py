"""
Legacy payment routes (/api/payments/*) — delegates to stripe_service.
"""
import logging
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user_from_access
from api.rate_limit import rate_limit
from api.stripe_service import (
    apply_subscription_state,
    create_checkout_session_for_user,
    process_stripe_webhook_event,
)
from config.settings import settings
from db.database import get_db
from db.models import AnalystProfile

logger = logging.getLogger(__name__)
router = APIRouter()

stripe.api_key = settings.stripe_secret_key


@router.get("/checkout-session")
async def create_checkout_session_get(
    tier: str,
    report_id: Optional[str] = None,
    return_url: Optional[str] = None,
    current_user: tuple = Depends(get_current_user_from_access),
    _rt: tuple = Depends(rate_limit("/api/payments/checkout-session")),
):
    """GET alias (legacy). Prefer POST /api/stripe/create-checkout."""
    user, _, _ = current_user
    try:
        if return_url:
            base = return_url.rstrip("/")
            success_url = f"{base}/dashboard?payment=success&session_id={{CHECKOUT_SESSION_ID}}"
            cancel_url = f"{base}/dashboard?payment=cancel"
            price_id = None
            from api.stripe_service import TIER_TO_PRICE

            tier_norm = tier.strip().lower()
            price_id = TIER_TO_PRICE.get(tier_norm)
            if not price_id:
                raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")
            session = stripe.checkout.Session.create(
                client_reference_id=str(user.id),
                success_url=success_url + (f"&report_id={report_id}" if report_id else ""),
                cancel_url=cancel_url + (f"&report_id={report_id}" if report_id else ""),
                payment_method_types=["card"],
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                metadata={"user_id": str(user.id), "tier": tier_norm},
                customer=user.stripe_customer_id if user.stripe_customer_id else None,
            )
        else:
            session = create_checkout_session_for_user(user, tier, report_id=report_id)
        return {"url": session.url, "session_id": session.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Checkout error: %s", e)
        raise HTTPException(status_code=500, detail="Checkout creation failed") from e


@router.post("/create-checkout")
async def create_checkout_post(
    data: dict,
    current_user: tuple = Depends(get_current_user_from_access),
    _rt: tuple = Depends(rate_limit("/api/payments/create-checkout")),
):
    """POST alias → same as /api/stripe/create-checkout."""
    tier = data.get("tier")
    if not tier:
        raise HTTPException(status_code=400, detail="tier is required")
    user, _, _ = current_user
    try:
        session = create_checkout_session_for_user(user, tier)
        return {"url": session.url, "session_id": session.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Checkout error: %s", e)
        raise HTTPException(status_code=500, detail="Checkout creation failed") from e


@router.post("/portal-session")
async def create_portal_session(
    current_user: tuple = Depends(get_current_user_from_access),
    _rt: tuple = Depends(rate_limit("/api/payments/portal-session")),
):
    user, _, _ = current_user
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No subscription history found.")

    try:
        base = settings.domain_url.rstrip("/")
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=f"{base}/dashboard",
        )
        return {"url": session.url}
    except Exception as e:
        logger.error("Portal error: %s", e)
        raise HTTPException(status_code=500, detail="Portal creation failed") from e


@router.post("/cancel")
async def cancel_subscription_alias(
    current_user: tuple = Depends(get_current_user_from_access),
):
    """Frontend alias for billing portal."""
    return await create_portal_session(current_user)


@router.post("/webhook")
async def stripe_webhook_legacy(request: Request, db: AsyncSession = Depends(get_db)):
    """Legacy webhook path — same handler as /api/stripe/webhook."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid signature") from e
    return await process_stripe_webhook_event(db, event)


@router.post("/confirm-session")
async def confirm_checkout_session(
    data: dict,
    current_user: tuple = Depends(get_current_user_from_access),
    db: AsyncSession = Depends(get_db),
):
    session_id = data.get("session_id")
    user, _, _ = current_user
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status == "paid" and session.client_reference_id == str(user.id):
            subscription = stripe.Subscription.retrieve(session.subscription)
            await apply_subscription_state(db, user, subscription)
            await db.commit()
            return {"status": "success", "tier": user.subscription_tier}
        raise HTTPException(status_code=400, detail="Invalid session or mismatched owner")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
