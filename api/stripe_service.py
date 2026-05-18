"""
Stripe subscription helpers (checkout, webhooks, tier sync).
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

import stripe
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_password_hash
from config.settings import settings
from db.models import AnalystProfile, StripeEvent

logger = logging.getLogger(__name__)

stripe.api_key = settings.stripe_secret_key

PRICE_TO_TIER = {
    settings.stripe_price_id_pro: "pro",
    settings.stripe_price_id_experts: "experts",
}
TIER_TO_PRICE = {v: k for k, v in PRICE_TO_TIER.items()}
ALLOWED_CHECKOUT_TIERS = frozenset({"pro", "experts"})


def checkout_redirect_urls() -> Tuple[str, str]:
    base = settings.domain_url.rstrip("/")
    success = f"{base}/dashboard?payment=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel = f"{base}/dashboard?payment=cancel"
    return success, cancel


def resolve_tier_from_price_id(price_id: str) -> str:
    return PRICE_TO_TIER.get(price_id, "free")


async def is_event_processed(db: AsyncSession, event_id: str) -> bool:
    stmt = select(StripeEvent).where(StripeEvent.event_id == event_id)
    result = await db.execute(stmt)
    return result.scalars().first() is not None


async def apply_subscription_state(
    db: AsyncSession, analyst: AnalystProfile, subscription: stripe.Subscription
) -> None:
    """Sync AnalystProfile from Stripe subscription (DB source for non-admin effective tier)."""
    price_id = subscription["items"]["data"][0]["price"]["id"]
    tier = resolve_tier_from_price_id(price_id)

    if subscription.status in ("active", "trialing"):
        analyst.subscription_tier = tier
    else:
        analyst.subscription_tier = "free"

    analyst.stripe_customer_id = subscription.customer
    analyst.stripe_subscription_id = subscription.id
    analyst.subscription_expires_at = datetime.fromtimestamp(
        subscription.current_period_end, tz=timezone.utc
    )
    logger.info(
        "Stripe sync analyst=%s tier=%s status=%s",
        analyst.id,
        analyst.subscription_tier,
        subscription.status,
    )


async def downgrade_analyst_to_free(db: AsyncSession, analyst: AnalystProfile) -> None:
    analyst.subscription_tier = "free"
    analyst.subscription_expires_at = datetime.now(timezone.utc)
    analyst.stripe_subscription_id = None
    logger.info("Stripe downgrade analyst=%s to free", analyst.id)


async def get_profile_by_customer(
    db: AsyncSession, customer_id: str
) -> Optional[AnalystProfile]:
    stmt = select(AnalystProfile).where(AnalystProfile.stripe_customer_id == customer_id)
    return (await db.execute(stmt)).scalars().first()


def normalize_checkout_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def extract_checkout_email(session_or_event: dict) -> Optional[str]:
    """Resolve payer email from a Checkout Session object."""
    details = session_or_event.get("customer_details") or {}
    email = details.get("email") or session_or_event.get("customer_email")
    if not email:
        meta = session_or_event.get("metadata") or {}
        email = meta.get("checkout_email")
    return normalize_checkout_email(email) if email else None


async def get_profile_by_email(db: AsyncSession, email: str) -> Optional[AnalystProfile]:
    normalized = normalize_checkout_email(email)
    if not normalized:
        return None
    stmt = select(AnalystProfile).where(AnalystProfile.email == normalized)
    return (await db.execute(stmt)).scalars().first()


async def provision_analyst_for_checkout(
    db: AsyncSession,
    email: str,
    *,
    subscription: Optional[Any] = None,
    tier_fallback: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> AnalystProfile:
    """
    Find or create AnalystProfile by email, then apply subscription tier from Stripe.
    New accounts get a random password; user sets password via complete-signup after checkout.
    """
    normalized = normalize_checkout_email(email)
    if not normalized or "@" not in normalized:
        raise ValueError("Valid checkout email required")

    analyst = await get_profile_by_email(db, normalized)
    if not analyst:
        analyst = AnalystProfile(
            email=normalized,
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            user_role="analyst",
            is_admin=False,
            subscription_tier="free",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(analyst)
        await db.flush()
        logger.info("Stripe provision: created analyst for %s", normalized)

    if customer_id and not analyst.stripe_customer_id:
        analyst.stripe_customer_id = customer_id

    if subscription:
        await apply_subscription_state(db, analyst, subscription)
    elif tier_fallback in ALLOWED_CHECKOUT_TIERS:
        analyst.subscription_tier = tier_fallback

    return analyst


async def get_profile_by_id(db: AsyncSession, analyst_id: str) -> Optional[AnalystProfile]:
    try:
        uid = uuid.UUID(analyst_id)
    except ValueError:
        return None
    stmt = select(AnalystProfile).where(AnalystProfile.id == uid)
    return (await db.execute(stmt)).scalars().first()


def create_guest_checkout_session(email: str, tier: str) -> stripe.checkout.Session:
    """Checkout for visitors without an account (email collected by Stripe)."""
    tier_norm = (tier or "").strip().lower()
    if tier_norm not in ALLOWED_CHECKOUT_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier. Allowed: {sorted(ALLOWED_CHECKOUT_TIERS)}",
        )

    price_id = TIER_TO_PRICE.get(tier_norm)
    if not price_id:
        raise HTTPException(status_code=400, detail="Stripe price not configured for tier")

    normalized = normalize_checkout_email(email)
    if not normalized or "@" not in normalized:
        raise HTTPException(status_code=400, detail="Valid email is required for checkout")

    success_url, cancel_url = checkout_redirect_urls()
    return stripe.checkout.Session.create(
        success_url=success_url,
        cancel_url=cancel_url,
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        customer_email=normalized,
        metadata={"tier": tier_norm, "checkout_email": normalized, "guest_checkout": "true"},
    )


def create_checkout_session_for_user(
    user: AnalystProfile,
    tier: str,
    *,
    report_id: Optional[str] = None,
) -> stripe.checkout.Session:
    tier_norm = (tier or "").strip().lower()
    if tier_norm not in ALLOWED_CHECKOUT_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier. Allowed: {sorted(ALLOWED_CHECKOUT_TIERS)}",
        )

    price_id = TIER_TO_PRICE.get(tier_norm)
    if not price_id:
        raise HTTPException(status_code=400, detail="Stripe price not configured for tier")

    success_url, cancel_url = checkout_redirect_urls()
    if report_id:
        success_url += f"&report_id={report_id}"
        cancel_url += f"&report_id={report_id}"

    return stripe.checkout.Session.create(
        client_reference_id=str(user.id),
        success_url=success_url,
        cancel_url=cancel_url,
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        metadata={"user_id": str(user.id), "tier": tier_norm},
        customer=user.stripe_customer_id if user.stripe_customer_id else None,
        customer_email=user.email if not user.stripe_customer_id else None,
    )


async def process_stripe_webhook_event(db: AsyncSession, event: dict) -> dict:
    """Handle Stripe webhook with idempotency."""
    event_id = event["id"]
    event_type = event["type"]
    data_object = event.get("data", {}).get("object", {})

    try:
        async with db.begin():
            if await is_event_processed(db, event_id):
                logger.info("Webhook skip (duplicate): %s", event_id)
                return {"status": "already_processed"}

            logger.info("Webhook processing: %s (%s)", event_type, event_id)

            if event_type == "checkout.session.completed":
                meta = data_object.get("metadata") or {}
                analyst_id = (
                    data_object.get("client_reference_id")
                    or meta.get("user_id")
                    or meta.get("analyst_id")
                )
                sub_id = data_object.get("subscription")
                customer_id = data_object.get("customer")
                subscription = (
                    stripe.Subscription.retrieve(sub_id) if sub_id else None
                )
                tier_meta = (meta.get("tier") or "").lower()
                checkout_email = extract_checkout_email(data_object)

                analyst: Optional[AnalystProfile] = None
                if analyst_id:
                    analyst = await get_profile_by_id(db, str(analyst_id))

                if analyst:
                    if customer_id and not analyst.stripe_customer_id:
                        analyst.stripe_customer_id = customer_id
                    if subscription:
                        await apply_subscription_state(db, analyst, subscription)
                    elif tier_meta in ALLOWED_CHECKOUT_TIERS:
                        analyst.subscription_tier = tier_meta
                elif checkout_email:
                    await provision_analyst_for_checkout(
                        db,
                        checkout_email,
                        subscription=subscription,
                        tier_fallback=tier_meta if tier_meta in ALLOWED_CHECKOUT_TIERS else None,
                        customer_id=customer_id,
                    )

            elif event_type in ("customer.subscription.updated", "invoice.paid"):
                sub_id = (
                    data_object.get("subscription")
                    if event_type == "invoice.paid"
                    else data_object.get("id")
                )
                if sub_id:
                    subscription = stripe.Subscription.retrieve(sub_id)
                    analyst = await get_profile_by_customer(db, subscription.customer)
                    if analyst:
                        await apply_subscription_state(db, analyst, subscription)

            elif event_type == "customer.subscription.deleted":
                customer_id = data_object.get("customer")
                if customer_id:
                    analyst = await get_profile_by_customer(db, customer_id)
                    if analyst:
                        await downgrade_analyst_to_free(db, analyst)

            db.add(StripeEvent(event_id=event_id, event_type=event_type))

        return {"status": "success"}

    except IntegrityError as e:
        err_msg = str(e).lower()
        if "uq_stripe_event_id" in err_msg or (
            "stripe_events" in err_msg and "event_id" in err_msg
        ):
            return {"status": "already_processed"}
        logger.error("Webhook integrity error: %s", e)
        raise HTTPException(status_code=500, detail="Database integrity violation") from e
    except Exception as e:
        logger.error("Webhook failed (%s): %s", event_type, e)
        raise HTTPException(status_code=500, detail="Webhook processing failed") from e
