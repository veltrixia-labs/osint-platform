from fastapi import FastAPI, Query, HTTPException, Depends, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.future import select
from sqlalchemy import desc, func
from db.models import AlertLog, AlertDelivery, AnalystProfile, Report
from db.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import os
import uuid
import logging
import json

from api.auth import (
    get_password_hash, verify_password, create_access_token, 
    create_refresh_token, get_current_user_from_access, refresh_tokens,
    session_manager, blacklist_manager, SecurityLogger
)

from api.payments import router as payments_router

# Config
API_PORT = int(os.getenv("API_PORT", 8000))
WEB_PORT = int(os.getenv("WEB_PORT", 5173))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", f"http://localhost:{WEB_PORT}").split(",")

app = FastAPI(title="OSINT Risk Analytics API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(payments_router, prefix="/api/payments", tags=["payments"])

# --- Auth Endpoints ---

@app.post("/api/auth/login")
async def login(response: Response, request: Request, data: dict, db: AsyncSession = Depends(get_db)):
    chat_id = data.get("telegram_chat_id")
    password = data.get("password")
    
    stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == chat_id)
    user = (await db.execute(stmt)).scalar_one_or_none()
    
    if not user or not verify_password(password, user.hashed_password):
        await SecurityLogger.log_event(db, "login_failed", details={"chat_id": chat_id}, client_ip=request.client.host)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    session_id = await session_manager.create_session(db, user.id)
    version = 1 # Initial version
    
    access_token = create_access_token({"sub": str(user.id), "session_id": str(session_id), "v": version})
    refresh_token, jti = create_refresh_token(user.id, session_id, version)
    
    # Set Refresh Token in HttpOnly Cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=os.getenv("ENV") == "production",
        samesite="lax",
        path="/api/auth",
        max_age=7 * 86400
    )
    
    await SecurityLogger.log_event(db, "login_success", user_id=user.id, session_id=session_id, client_ip=request.client.host)
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/api/auth/refresh")
async def refresh(auth_data: dict = Depends(refresh_tokens)):
    return auth_data

@app.post("/api/auth/logout")
async def logout(response: Response, request: Request, current_user_data: tuple = Depends(get_current_user_from_access), db: AsyncSession = Depends(get_db)):
    user, session_id, _ = current_user_data
    await session_manager.blacklist.revoke_session(db, session_id, reason="User logout", bump_version=True)
    response.delete_cookie(key="refresh_token", path="/api/auth")
    await SecurityLogger.log_event(db, "logout", user_id=user.id, session_id=session_id, client_ip=request.client.host)
    return {"status": "success"}

@app.get("/api/auth/me")
async def get_me(current_user_data: tuple = Depends(get_current_user_from_access)):
    user, _, _ = current_user_data
    return {
        "id": str(user.id),
        "chat_id": user.telegram_chat_id,
        "role": user.user_role,
        "tier": user.subscription_tier,
        "expires_at": user.subscription_expires_at.isoformat() if user.subscription_expires_at else None
    }

# --- Protected Intelligence Endpoints ---

from api.gating import (
    requires_tier, requires_role, get_effective_tier,
    TIER_FREE, TIER_PRO, TIER_ENTERPRISE,
    get_plan_limits, get_watchlist_limit, get_alert_limit,
    is_topic_allowed, can_access_report_type, can_add_watchlist_keywords,
    get_allowed_topics, get_restricted_topics,
)
from api.rate_limit import rate_limit

@app.get("/api/alerts")
async def get_alerts(
    severity: Optional[str] = None,
    suppressed: Optional[bool] = None,
    analyst_id: Optional[uuid.UUID] = None,
    topic: Optional[str] = None,
    limit: int = 20,
    since: Optional[datetime] = None,
    current_user: tuple = Depends(rate_limit("/api/alerts")),
    db: AsyncSession = Depends(get_db)
):
    user = current_user  # rate_limit() returns AnalystProfile directly
    tier = await get_effective_tier(user)

    # ── Topic gating ──────────────────────────────────────────────────────
    if topic and not is_topic_allowed(tier, topic):
        raise HTTPException(
            status_code=403,
            detail=f"Topic '{topic}' requires a higher subscription tier. "
                   f"Your plan ({tier}) allows: {', '.join(get_allowed_topics(tier))}"
        )

    # Caching Logic
    cache_key = f"alerts:{severity}:{suppressed}:{analyst_id}:{topic}:{limit}:{since}"
    if await blacklist_manager._is_redis_available():
        try:
            cached = await blacklist_manager.redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except:
            pass

    stmt = select(AlertLog)
    if analyst_id:
        stmt = stmt.join(AlertDelivery).where(AlertDelivery.analyst_id == analyst_id)

    if topic:
        stmt = stmt.where(AlertLog.topic == topic)
    if severity:
        stmt = stmt.where(AlertLog.severity == severity)
    if suppressed is not None:
        stmt = stmt.where(AlertLog.suppressed == suppressed)
    if since:
        stmt = stmt.where(AlertLog.triggered_at >= since)

    stmt = stmt.order_by(desc(AlertLog.triggered_at)).limit(limit)
    results = (await db.execute(stmt)).scalars().all()

    formatted = [
        {
            "id": str(log.id),
            "severity": log.severity,
            "topic": log.topic,
            "intelligence_score": log.intelligence_score,
            "created_at": log.triggered_at.isoformat(),
            "suppressed": log.suppressed,
            "metadata": log.metadata_json
        } for log in results
    ]

    # Store in Cache (60s TTL)
    if await blacklist_manager._is_redis_available():
        try:
            await blacklist_manager.redis_client.setex(cache_key, 60, json.dumps(formatted))
        except:
            pass

    return formatted

@app.post("/api/alerts/{alert_id}/feedback")
async def submit_feedback(
    alert_id: uuid.UUID, 
    data: dict, 
    current_user: tuple = Depends(rate_limit()),
    db: AsyncSession = Depends(get_db)
):
    score = data.get("score")
    if not score or not (1 <= score <= 5):
        raise HTTPException(status_code=400, detail="Score must be 1-5")
    
    stmt = select(AlertLog).where(AlertLog.id == alert_id)
    alert = (await db.execute(stmt)).scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
        
    alert.feedback_score = score
    await db.commit()
    return {"status": "success"}

@app.get("/api/analysts")
async def get_analysts(
    current_user: tuple = Depends(get_current_user_from_access),
    db: AsyncSession = Depends(get_db)
):
    # RBAC: Only admin can see all analysts profile details maybe? 
    # For now, allow all authenticated
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

@app.post("/api/analysts/{analyst_id}/watchlist")
async def update_watchlist(
    analyst_id: uuid.UUID, 
    data: dict, 
    current_user: tuple = Depends(rate_limit()),
    db: AsyncSession = Depends(get_db)
):
    # RBAC: Analyst can only update their own watchlist unless admin
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

@app.get("/api/reports/{report_id}")
async def get_report_detail(
    report_id: uuid.UUID,
    current_user: tuple = Depends(get_current_user_from_access),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve a specific report by ID (Phase 34 Routing)."""
    stmt = select(Report).where(Report.id == report_id)
    report = (await db.execute(stmt)).scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
        
    return {
        "id": str(report.id),
        "report_type": report.report_type,
        "topic_code": report.topic_code,
        "content_markdown": report.content_markdown,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "substack_url": report.substack_draft_url,
        "period_days": report.period_days
    }

@app.get("/api/public/reports/{report_id}")
async def get_public_report_preview(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve a public truncated preview of a report (no auth required)."""
    stmt = select(Report).where(Report.id == report_id)
    report = (await db.execute(stmt)).scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Generate Preview: First 3 paragraphs or max 1000 characters
    content = report.content_markdown or ""
    paragraphs = [p for p in content.split('\n\n') if p.strip()]
    preview_parts = paragraphs[:3]
    preview_text = "\n\n".join(preview_parts)
    
    # Apply char limit safety (1000 chars)
    if len(preview_text) > 1000:
        preview_text = preview_text[:1000] + "..."
        
    return {
        "id": str(report.id),
        "report_type": report.report_type,
        "topic_code": report.topic_code,
        "content_preview": preview_text,
        "is_preview": True,
        "created_at": report.created_at.isoformat() if report.created_at else None
    }

# ── Usage Endpoint (Phase 33) ─────────────────────────────────────────────────

@app.get("/api/system/usage")
async def get_usage(
    current_user: tuple = Depends(get_current_user_from_access),
    db: AsyncSession = Depends(get_db)
):
    """Return real-time usage statistics against the user's plan limits."""
    user, _, _ = current_user
    tier = await get_effective_tier(user)
    limits = get_plan_limits(tier)

    # alerts.used = successfully delivered alerts today (UTC)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    alerts_stmt = (
        select(func.count(AlertDelivery.id))
        .where(
            AlertDelivery.analyst_id == user.id,
            AlertDelivery.status == "delivered",
            AlertDelivery.delivered_at >= today_start,
        )
    )
    alerts_used = (await db.execute(alerts_stmt)).scalar() or 0

    # keywords.used = current watchlist size
    kw = user.watch_keywords
    keywords_used = len(kw) if isinstance(kw, list) else 0

    alert_limit = limits["alerts_per_day"]
    reports_cfg = limits["reports"]

    return {
        "tier": tier,
        "alerts": {
            "used": alerts_used,
            "limit": alert_limit if alert_limit != "unlimited" else -1,
        },
        "keywords": {
            "used": keywords_used,
            "limit": limits["watchlist_keywords"],
        },
        "topics": {
            "allowed": get_allowed_topics(tier),
            "restricted": get_restricted_topics(tier),
        },
        "reports": {
            "daily": True,
            "monthly": can_access_report_type(tier, "monthly"),
        },
    }

# ── System Health ─────────────────────────────────────────────────────────────

@app.get("/api/system/health")
async def get_system_metrics(
    current_user: tuple = Depends(get_current_user_from_access),
    db: AsyncSession = Depends(get_db)
):
    user, _, _ = current_user
    
    # Caching
    cache_key = f"metrics:{user.user_role}"
    if await blacklist_manager._is_redis_available():
        try:
            cached = await blacklist_manager.redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except:
            pass

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    
    total_stmt = select(func.count(AlertLog.id)).where(AlertLog.triggered_at >= week_ago)
    total = (await db.execute(total_stmt)).scalar() or 0
    
    reviewed_stmt = select(func.count(AlertLog.id)).where(AlertLog.triggered_at >= week_ago, AlertLog.feedback_score.isnot(None))
    reviewed = (await db.execute(reviewed_stmt)).scalar() or 0
    
    suppressed_stmt = select(func.count(AlertLog.id)).where(AlertLog.triggered_at >= week_ago, AlertLog.suppressed == True)
    suppressed = (await db.execute(suppressed_stmt)).scalar() or 0
    
    health_data = {
        "review_rate": round(reviewed / total if total > 0 else 0, 2),
        "suppression_ratio": round(suppressed / (total + suppressed) if (total + suppressed) > 0 else 0, 2),
    }

    if user.user_role == "admin":
        # Full Metrics for Admin
        trigger_stmt = select(
            AlertLog.trigger_type,
            func.avg(AlertLog.feedback_score)
        ).where(AlertLog.triggered_at >= week_ago, AlertLog.feedback_score.isnot(None)).group_by(AlertLog.trigger_type).order_by(desc(func.avg(AlertLog.feedback_score))).limit(5)
        top_triggers = (await db.execute(trigger_stmt)).all()
        
        health_data.update({
            "total_incidents": total,
            "top_performing_triggers": [{"type": t[0], "avg_feedback": round(t[1], 2)} for t in top_triggers],
            "system_status": "operational"
        })
    else:
        # Summary for Analyst
        health_data.update({
            "status_summary": "Active",
            "last_week_total": total
        })

    # Store in Cache (300s TTL)
    if await blacklist_manager._is_redis_available():
        try:
            await blacklist_manager.redis_client.setex(cache_key, 300, json.dumps(health_data))
        except:
            pass

    return health_data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
