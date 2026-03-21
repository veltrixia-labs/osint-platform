import os
import uuid
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from db.database import get_db
from db.models import AnalystProfile, StripeEvent
from api.auth import get_current_user_from_access
from api.rate_limit import rate_limit

import stripe
from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Stripe Configuration Initialization
stripe.api_key = settings.stripe_secret_key
DOMAIN_URL = settings.domain_url

# Price-to-Tier Mapping (Source of Truth)
PRICE_TO_TIER = {
    settings.stripe_price_id_pro: "pro",
}
TIER_TO_PRICE = {v: k for k, v in PRICE_TO_TIER.items()}

# --- INTERNAL HELPERS ---

def _resolve_tier_from_price_id(price_id: str) -> str:
    """地図からティアを特定。"""
    return PRICE_TO_TIER.get(price_id, "free")

async def _is_event_processed(db: AsyncSession, event_id: str) -> bool:
    """イベントが既に処理済みか確認（Idempotency）。"""
    stmt = select(StripeEvent).where(StripeEvent.event_id == event_id) # event_id カラムで検索
    result = await db.execute(stmt)
    return result.scalars().first() is not None

async def _record_event_processed(db: AsyncSession, event_id: str, event_type: str):
    """イベントの処理を記録。"""
    # 新しい StripeEvent モデル構造に対応 (UUID id は自動生成)
    event_log = StripeEvent(event_id=event_id, event_type=event_type)
    db.add(event_log)
    # db.begin() block will commit automatically at exit if no exception

async def _apply_subscription_state(db: AsyncSession, analyst: AnalystProfile, subscription: stripe.Subscription):
    """
    Stripe の Subscription を Source of Truth として同期。
    """
    price_id = subscription['items']['data'][0]['price']['id']
    tier = _resolve_tier_from_price_id(price_id)
    
    # 状態同期 (active/trialing のみ Pro 維持)
    # reference: https://stripe.com/docs/api/subscriptions/object#subscription_object-status
    if subscription.status in ["active", "trialing"]:
        analyst.subscription_tier = tier
    else:
        # canceled, past_due, unpaid, incomplete, incomplete_expired は free 扱い
        analyst.subscription_tier = "free"
            
    analyst.stripe_customer_id = subscription.customer
    analyst.stripe_subscription_id = subscription.id
    analyst.subscription_expires_at = datetime.fromtimestamp(subscription.current_period_end, tz=timezone.utc)
    
    logger.info(f"Sub-Sync [Analyst {analyst.id}]: tier={analyst.subscription_tier}, status={subscription.status}, expires_at={analyst.subscription_expires_at}")
    # Note: caller (webhook) handles the commit/transaction

async def _get_profile_by_customer(db: AsyncSession, customer_id: str) -> Optional[AnalystProfile]:
    stmt = select(AnalystProfile).where(AnalystProfile.stripe_customer_id == customer_id)
    return (await db.execute(stmt)).scalars().first()

# --- PUBLIC ENDPOINTS ---

@router.get("/checkout-session")
async def create_checkout_session(
    tier: str, 
    report_id: Optional[str] = None,
    return_url: Optional[str] = None,
    current_user: tuple = Depends(get_current_user_from_access), 
    _rt: tuple = Depends(rate_limit("/api/payments/checkout-session")), 
    db: AsyncSession = Depends(get_db)
):
    price_id = TIER_TO_PRICE.get(tier)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Invalid tier price: {tier}")
        
    user, _, _ = current_user
    try:
        base_domain = return_url.rstrip('/') if return_url else DOMAIN_URL
        success_url = f"{base_domain}/?payment=success&session_id={{CHECKOUT_SESSION_ID}}"
        if report_id: success_url += f"&report_id={report_id}"
        
        cancel_url = f"{base_domain}/?payment=cancel"
        if report_id: cancel_url += f"&report_id={report_id}"

        session = stripe.checkout.Session.create(
            client_reference_id=str(user.id),  # 重要: ユーザー特定の一番の根拠
            success_url=success_url,
            cancel_url=cancel_url,
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            metadata={
                "user_id": str(user.id), # 二重化
                "tier": tier
            },
            customer=user.stripe_customer_id if user.stripe_customer_id else None
        )
        return {"url": session.url, "session_id": session.id}
    except Exception as e:
        logger.error(f"Checkout error: {e}")
        raise HTTPException(status_code=500, detail="Checkout creation failed.")

@router.post("/portal-session")
async def create_portal_session(
    current_user: tuple = Depends(get_current_user_from_access),
    _rt: tuple = Depends(rate_limit("/api/payments/portal-session")), # レート制限追加
    db: AsyncSession = Depends(get_db)
):
    user, _, _ = current_user
    # 認可チェック: 自身の customer_id があるか確認
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No subscription history found.")

    try:
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=f"{DOMAIN_URL}/"
        )
        return {"url": session.url}
    except Exception as e:
        logger.error(f"Portal error: {e}")
        raise HTTPException(status_code=500, detail="Portal creation failed.")

@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    except Exception as e:
        logger.warning(f"Webhook signature fail: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_id = event['id']
    event_type = event['type']
    data_object = event.get('data', {}).get('object', {})

    try:
        # トランザクション化
        async with db.begin():
            # 1. 既処理チェック (Idempotency)
            if await _is_event_processed(db, event_id):
                logger.info(f"Webhook [Skip]: {event_id} already exists.")
                return {"status": "already_processed"}

            logger.info(f"Webhook [Atomic Processing]: {event_type} ({event_id})")
            
            # A. 課金完了 (紐付け優先順位の厳格化)
            if event_type == "checkout.session.completed":
                # 順序: client_reference_id -> user_id (metadata) -> analyst_id (metadata fallback)
                meta = data_object.get("metadata", {})
                analyst_id = (
                    data_object.get("client_reference_id") or 
                    meta.get("user_id") or 
                    meta.get("analyst_id")
                )
                if analyst_id:
                    stmt = select(AnalystProfile).where(AnalystProfile.id == uuid.UUID(analyst_id))
                    analyst = (await db.execute(stmt)).scalars().first()
                    if analyst:
                        sub_id = data_object.get("subscription")
                        if sub_id:
                            subscription = stripe.Subscription.retrieve(sub_id)
                            await _apply_subscription_state(db, analyst, subscription)

            # B. 状態同期
            elif event_type in ["customer.subscription.updated", "invoice.paid"]:
                sub_id = data_object.get("subscription") if event_type == "invoice.paid" else data_object.get("id")
                if sub_id:
                    subscription = stripe.Subscription.retrieve(sub_id)
                    analyst = await _get_profile_by_customer(db, subscription.customer)
                    if analyst:
                        await _apply_subscription_state(db, analyst, subscription)

            # C. 解約
            elif event_type == "customer.subscription.deleted":
                customer_id = data_object.get("customer")
                analyst = await _get_profile_by_customer(db, customer_id)
                if analyst:
                    analyst.subscription_tier = "free"
                    analyst.subscription_expires_at = datetime.now(timezone.utc)
                    logger.info(f"Analyst {analyst.id} downgraded (deleted)")

            # D. 重複防止レコード保存
            event_log = StripeEvent(event_id=event_id, event_type=event_type)
            db.add(event_log)
            # db.begin() block will commit automatically at exit if no exception

        return {"status": "success"}

    except IntegrityError as e:
        # StripeEvent.event_id の重複（同時登録）である場合のみ正常系として扱う。
        # 1. 制約名による明示的な判定を優先 (uq_stripe_event_id)
        # 2. 文字列検索による判定を fallback として保持
        err_msg = str(e).lower()
        is_event_collision = (
            "uq_stripe_event_id" in err_msg or 
            ("stripe_events" in err_msg and "event_id" in err_msg)
        )
        
        if is_event_collision:
            logger.info(f"Webhook [Skip-Race]: {event_id} already exists (concurrent insert).")
            return {"status": "already_processed"}
            
        logger.error(f"Webhook Atomic fail (IntegrityError): {e}")
        raise HTTPException(status_code=500, detail="Database integrity violation")

    except Exception as e:
        logger.error(f"Webhook Atomic fail ({event_type}): {e}")
        # async with db.begin() handles rollback on exception
        raise HTTPException(status_code=500, detail="Webhook processing failed")

@router.post("/confirm-session")
async def confirm_checkout_session(
    data: dict,
    current_user: tuple = Depends(get_current_user_from_access),
    db: AsyncSession = Depends(get_db)
):
    session_id = data.get("session_id")
    user, _, _ = current_user
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status == "paid" and session.client_reference_id == str(user.id):
            subscription = stripe.Subscription.retrieve(session.subscription)
            await _apply_subscription_state(db, user, subscription)
            await db.commit()
            return {"status": "success", "tier": user.subscription_tier}
        raise HTTPException(status_code=400, detail="Invalid session or mismatched owner")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
