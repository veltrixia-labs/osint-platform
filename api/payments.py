import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.database import get_db
from db.models import AnalystProfile
from api.auth import get_current_user_from_access
from api.rate_limit import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()

import stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
DOMAIN_URL = os.getenv("DOMAIN_URL", "http://localhost:8000")

# Prices mapping (in production, use real Stripe Price IDs)
PRICES = {
    "pro": "price_mock_pro",
    "enterprise": "price_mock_enterprise"
}

@router.get("/checkout-session")
async def create_checkout_session(
    tier: str, 
    current_user: tuple = Depends(get_current_user_from_access), 
    _rt: tuple = Depends(rate_limit("/api/payments/checkout-session")), 
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a Stripe Checkout session for a specific tier.
    Provides fallback to a mock system when no Stripe Key represents a development environment.
    """
    if tier not in PRICES:
        raise HTTPException(status_code=400, detail="Invalid tier")
        
    # Get analyst profile from validated user tuple
    user, _, _ = current_user
    analyst = user  # already an AnalystProfile object from the auth dep

    if not stripe.api_key:
        logger.warning("Stripe key missing. Generates MOCK checkout url.")
        analyst.subscription_tier = tier
        analyst.stripe_customer_id = "cus_mock_123"
        analyst.stripe_subscription_id = "sub_mock_456"
        analyst.subscription_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        await db.commit()
        return {"success": True, "plan": tier}

    try:
        checkout_session = stripe.checkout.Session.create(
            customer=analyst.stripe_customer_id,
            client_reference_id=str(analyst.id),
            success_url=DOMAIN_URL + "/dashboard?payment=success&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=DOMAIN_URL + "/dashboard?payment=canceled",
            payment_method_types=["card"],
            mode="subscription",
            line_items=[
                {
                    "price": PRICES[tier],
                    "quantity": 1,
                }
            ],
            metadata={
                "tier": tier,
                "analyst_id": str(analyst.id)
            }
        )
        return {"url": checkout_session.url}
    except Exception as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Stripe Webhook literal handler for subscription fulfillment and downgrade detection.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    
    event = None

    if stripe.api_key and endpoint_secret:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            raise HTTPException(status_code=400, detail="Invalid signature")
    elif os.getenv("ENV") != "production":
        # Mock webhook handling for local integration tests
        import json
        try:
            event = json.loads(payload)
        except:
            raise HTTPException(status_code=400, detail="Failed to parse mock JSON body")
    else:
        raise HTTPException(status_code=503, detail="Payment processing unavailable")

    logger.info(f"Processing webhook event: {event.get('type')}")
    
    # Handle the event sequences
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        
        analyst_id = session.get("client_reference_id") or session.get("metadata", {}).get("analyst_id")
        tier = session.get("metadata", {}).get("tier", "pro")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        
        if analyst_id:
            logger.info(f"Fulfilling subscription {tier} for analyst ID {analyst_id}")
            try:
                analyst_uuid = uuid.UUID(str(analyst_id))
            except (ValueError, AttributeError):
                logger.warning(f"Invalid analyst_id in webhook: {analyst_id}")
                return {"status": "success"}
            stmt = select(AnalystProfile).where(AnalystProfile.id == analyst_uuid)
            analyst = (await db.execute(stmt)).scalars().first()
            if analyst:
                analyst.subscription_tier = tier
                analyst.stripe_customer_id = customer_id
                analyst.stripe_subscription_id = subscription_id
                analyst.subscription_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                await db.commit()

    elif event["type"] in ["customer.subscription.deleted", "customer.subscription.canceled"]:
        session = event["data"]["object"]
        customer_id = session.get("customer")
        
        if customer_id:
            logger.info(f"Downgrading subscription for Stripe Customer {customer_id}")
            stmt = select(AnalystProfile).where(AnalystProfile.stripe_customer_id == customer_id)
            analyst = (await db.execute(stmt)).scalars().first()
            if analyst:
                analyst.subscription_tier = "free"
                analyst.subscription_expires_at = datetime.now(timezone.utc)
                await db.commit()

    return {"status": "success"}

@router.get("/mock/checkout-success")
async def mock_checkout_success(tier: str, analyst_id: str, db: AsyncSession = Depends(get_db)):
    """A developer convenience route to verify database upgrade actions without real Stripe."""
    try:
        analyst_uuid = uuid.UUID(analyst_id)
    except (ValueError, AttributeError):
        return {"status": "success", "message": "Invalid analyst_id"}
    stmt = select(AnalystProfile).where(AnalystProfile.id == analyst_uuid)
    analyst = (await db.execute(stmt)).scalars().first()
    if analyst:
        analyst.subscription_tier = tier
        analyst.stripe_customer_id = "cus_mock_123"
        analyst.stripe_subscription_id = "sub_mock_456"
        analyst.subscription_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        await db.commit()
    return {"status": "success", "message": f"Mock upgraded analyst to {tier}"}
