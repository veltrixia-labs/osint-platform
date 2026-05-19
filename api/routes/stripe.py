"""
Stripe checkout and webhook endpoints (/api/stripe/*).
"""
import logging
import os
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import (
    create_access_token,
    create_refresh_token,
    get_optional_current_user,
    get_password_hash,
    session_manager,
)
from api.rate_limit import rate_limit
from api.stripe_service import (
    create_checkout_session_for_user,
    create_guest_checkout_session,
    extract_checkout_email,
    get_profile_by_email,
    normalize_checkout_email,
    process_stripe_webhook_event,
    provision_analyst_for_checkout,
)
from config.settings import settings
from db.database import get_db
from db.models import AnalystProfile

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stripe"])


class CreateCheckoutRequest(BaseModel):
    tier: str = Field(..., description="pro or experts")
    billing: str = Field(
        default="monthly",
        description="monthly or annual — selects the Stripe Price ID",
    )
    email: Optional[str] = Field(
        default=None,
        description="Required for guest checkout when not logged in",
    )


class StripeCompleteSignupRequest(BaseModel):
    session_id: str
    password: str = Field(..., min_length=8)


@router.post("/create-checkout")
async def create_checkout(
    body: CreateCheckoutRequest,
    current_user: Optional[AnalystProfile] = Depends(get_optional_current_user),
    _rt: Optional[AnalystProfile] = Depends(rate_limit("/api/stripe/create-checkout")),
):
    """
    Create Stripe Checkout. Logged-in users bind client_reference_id; guests pass email.
    """
    user = current_user[0] if isinstance(current_user, tuple) else current_user

    try:
        if user:
            session = create_checkout_session_for_user(
                user, body.tier, billing=body.billing
            )
        else:
            email = normalize_checkout_email(body.email)
            if not email:
                raise HTTPException(
                    status_code=400,
                    detail="email is required when not logged in",
                )
            session = create_guest_checkout_session(
                email, body.tier, billing=body.billing
            )
        return {"url": session.url, "session_id": session.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Stripe create-checkout failed: %s", e)
        raise HTTPException(status_code=500, detail="Checkout creation failed") from e


@router.post("/complete-signup")
async def complete_stripe_signup(
    body: StripeCompleteSignupRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    After guest checkout: set password on the provisioned account and return JWT.
    """
    try:
        session = stripe.checkout.Session.retrieve(body.session_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid checkout session") from e

    if session.payment_status != "paid":
        raise HTTPException(status_code=400, detail="Checkout not completed")

    email = extract_checkout_email(session)
    if not email:
        raise HTTPException(status_code=400, detail="No email on checkout session")

    analyst = await get_profile_by_email(db, email)
    if not analyst:
        sub_id = session.get("subscription")
        subscription = (
            stripe.Subscription.retrieve(sub_id) if sub_id else None
        )
        tier_meta = (session.metadata or {}).get("tier")
        analyst = await provision_analyst_for_checkout(
            db,
            email,
            subscription=subscription,
            tier_fallback=tier_meta,
            customer_id=session.get("customer"),
        )

    analyst.hashed_password = get_password_hash(body.password)
    await db.commit()

    session_id = await session_manager.create_session(db, analyst.id)
    version = 1
    access_token = create_access_token(
        {"sub": str(analyst.id), "session_id": str(session_id), "v": version}
    )
    refresh_token, _jti = create_refresh_token(analyst.id, session_id, version)

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=os.getenv("ENV", "development").lower() == "production",
        samesite="lax",
        path="/api/auth",
        max_age=7 * 86400,
    )

    return {
        "status": "ok",
        "access_token": access_token,
        "token_type": "bearer",
        "email": analyst.email,
        "tier": analyst.subscription_tier,
    }


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
