from fastapi import FastAPI, Query, HTTPException, Depends, Request, Response, status
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.future import select
from sqlalchemy import desc, func
from db.models import AlertLog, AlertDelivery, AnalystProfile, Report, AnalyticsEvent, SystemMetric
from db.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import os
import uuid
import logging
import json
from dotenv import load_dotenv

load_dotenv()

# OSINT RISK INTELLIGENCE API

from api.auth import (
    get_password_hash, verify_password, create_access_token, 
    create_refresh_token, get_current_user_from_access, refresh_tokens,
    get_optional_current_user,
    session_manager, blacklist_manager, SecurityLogger
)
from api.payments import router as payments_router
from api.gating import (
    get_effective_tier, get_watchlist_limit, can_add_watchlist_keywords,
    TIER_PRO, TIER_EXPERTS, TIER_ORDER, is_tier_sufficient
)
from db.enums import ReportType

# Production Traceability
COMMIT_HASH = os.getenv("RENDER_GIT_COMMIT", "a7bf299") # Fallback to a7bf299 for now
DEPLOY_TIMESTAMP = os.getenv("RENDER_MOD_TIME", datetime.now(timezone.utc).isoformat())

app = FastAPI(title="OSINT Risk Analytics API")
logger = logging.getLogger(__name__)

# [Robustness] Ensure all tables exist at startup (Alembic Migration Runner)
try:
    from db.database import Base, AsyncSessionLocal, run_migrations
    from db.seeding import seed_admin
    import asyncio
    
    # 1. Run Alembic Migrations
    run_migrations()

    # 2. Seed Admin User (Async)
    async def run_seed():
        async with AsyncSessionLocal() as session:
            await seed_admin(session)
    
    asyncio.create_task(run_seed())

except Exception as e:
    logger.error(f"Error during API startup initialization: {e}")


logger.info("--- OSINT SCHEDULER STARTUP ---")
logger.info("SCHEDULER_V2_ACTIVE: SUCCESS_ASYNC_NATIVE")
logger.info(f"--- OSINT API BOOTING [Version: {COMMIT_HASH}] ---")

@app.get("/")
async def root():
    return {"status": "ok", "message": "OSINT API is running", "version": COMMIT_HASH}

@app.get("/healthz")
async def healthz():
    return {"status": "healthy"}

@app.get("/api/health")
async def get_system_health(db: AsyncSession = Depends(get_db)):
    """Comprehensive health check for monitoring tools."""
    # 1. DB Ping
    try:
        await db.execute(select(1))
        db_status = "connected"
    except Exception as e:
        db_status = f"unhealthy: {e}"

    # 2. Scheduler Heartbeat Check
    stmt = select(SystemMetric).where(SystemMetric.metric_key == "scheduler_heartbeat")
    res = await db.execute(stmt)
    heartbeat = res.scalar_one_or_none()
    
    scheduler_status = "unknown"
    if heartbeat:
        last_run = datetime.fromisoformat(heartbeat.metric_value)
        if datetime.now(timezone.utc) - last_run < timedelta(minutes=10):
            scheduler_status = "active"
        else:
            scheduler_status = f"stale (Last: {heartbeat.metric_value})"

    is_healthy = db_status == "connected" and scheduler_status == "active"
    
    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "database": db_status,
        "scheduler": scheduler_status,
        "version": COMMIT_HASH,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/metrics")
async def get_all_metrics(db: AsyncSession = Depends(get_db)):
    """Expose system metrics for dashboard/monitoring."""
    stmt = select(SystemMetric)
    result = await db.execute(stmt)
    metrics = result.scalars().all()
    
    return {m.metric_key: m.metric_value for m in metrics}

@app.get("/api/version")
async def get_version():
    """Definitive production version check."""
    return {
        "commit": COMMIT_HASH,
        "deployed_at": DEPLOY_TIMESTAMP,
        "status": "V1_CLEANUP_ACTIVE",
        "diagnostic_filter": "STRICT_ORM_V1",
        "debug_info": {
            "cwd": os.getcwd(),
            "base_dir": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "dist_exists": os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web_dashboard", "dist"))
        }
    }

@app.get("/api/reports/sample")
async def get_reports_sample(db: AsyncSession = Depends(get_db)):
    """Internal debug endpoint to verify raw report presence."""
    stmt = select(Report).order_by(Report.created_at.desc()).limit(3)
    result = await db.execute(stmt)
    reports = result.scalars().all()
    return [{"id": str(r.id), "type": r.report_type, "topic": r.topic_code, "title": r.title} for r in reports]

# Config
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", 8000)))
WEB_PORT = int(os.getenv("WEB_PORT", 5173))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", f"http://localhost:{WEB_PORT}").split(",")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

app.include_router(payments_router, prefix="/api/payments", tags=["payments"])

# --- Static File Serving (Moved to bottom) ---

# --- Auth Endpoints ---

@app.post("/api/auth/login")
async def login(response: Response, request: Request, data: dict, db: AsyncSession = Depends(get_db)):
    chat_id = data.get("telegram_chat_id")
    password = data.get("password")
    
    logger.info(f"Login attempt for chat_id: {chat_id}")
    stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == chat_id)
    user = (await db.execute(stmt)).scalar_one_or_none()
    
    if not user:
        logger.warning(f"Login failed: User not found for chat_id: {chat_id}")
        await SecurityLogger.log_event(db, "login_failed", details={"chat_id": chat_id, "reason": "user_not_found"}, client_ip=request.client.host)
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    if not verify_password(password, user.hashed_password):
        logger.warning(f"Login failed: Password mismatch for chat_id: {chat_id}")
        await SecurityLogger.log_event(db, "login_failed", details={"chat_id": chat_id, "reason": "password_mismatch"}, client_ip=request.client.host)
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

class AnalyticsEventCreate(BaseModel):
    event_type: str
    report_id: Optional[uuid.UUID] = None
    metadata_json: Optional[dict] = None

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

    # Filter: Allow if has verified domains OR High Intensity OR has supporting events
    # (Requirement: Prevent high-signal alerts from being suppressed by strict evidence checks)
    filtered_results = []
    for log in results:
        metadata = log.metadata_json or {}
        domain_count = metadata.get("domain_count", 0)
        
        # New multi-tier filtering logic
        if domain_count > 0:
            filtered_results.append(log)
        elif log.intensity >= 8.0:
            filtered_results.append(log)
        elif getattr(log, "supporting_events_count", 0) > 0:
            filtered_results.append(log)

    formatted = [
        {
            "id": str(log.id),
            "severity": log.severity,
            "target_label": log.target_label,
            "topic": log.topic,
            "trigger_type": log.trigger_type,
            "intelligence_score": log.intelligence_score,
            "intensity": log.intensity,
            "triggered_at": log.triggered_at.isoformat(),
            "suppressed": log.suppressed,
            "related_report_id": str(log.related_report_id) if log.related_report_id else None,
            "domain_count": log.metadata_json.get("domain_count", 0) if log.metadata_json else 0,
            "evidence_list": log.metadata_json.get("evidence_list", []),
            "spike_delta": log.metadata_json.get("spike_delta", 0.0) if log.metadata_json else 0.0,
            "metadata": log.metadata_json
        } for log in filtered_results
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
    """Retrieve a specific report by ID (Strict Plan Gating)."""
    stmt = select(Report).where(Report.id == report_id)
    report = (await db.execute(stmt)).scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
        
    user, _, _ = current_user
    tier = await get_effective_tier(user)
    
    # ── Strict Plan Gating ────────────────────────────────────────────────
    plan_required = report.plan_required or "free"
    if not is_tier_sufficient(tier, plan_required) and user.user_role != "admin":
        raise HTTPException(
            status_code=403, 
            detail=f"Subscription upgrade required. This report requires the '{plan_required}' plan."
        )
    # ──────────────────────────────────────────────────────────────────────

    return {
        "id": str(report.id),
        "report_type": report.report_type,
        "topic_code": report.topic_code,
        "content_markdown": report.content_markdown,
        "title": report.title or f"{report.topic_code} Briefing",
        "teaser_md": report.teaser_md,
        "locked": False,
        "is_premium": report.is_premium,
        "source_count": report.source_count or 0,
        "confidence_level": str(report.confidence_level or "Low"),
        "created_at": report.created_at.isoformat() if hasattr(report.created_at, 'isoformat') else report.created_at,
        "plan_required": plan_required
    }

@app.get("/api/reports")
async def list_reports(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: tuple = Depends(get_current_user_from_access),
    limit: int = 10,
    topic: Optional[str] = None
):
    response.headers["X-API-Version"] = "2026-03-24-REBRAND-V1"
    user, _, _ = current_user
    tier = await get_effective_tier(user)

    try:
        # 1. SQLAlchemy ORM Filter (Strict)
        stmt = select(Report).where(
            (Report.report_type != ReportType.SYSTEM_DIAGNOSTIC.value) &
            (Report.report_type != "system") &
            (Report.topic_code != "system")
        )
        
        if topic:
            stmt = stmt.where(Report.topic_code == topic)
            
        stmt = stmt.order_by(Report.created_at.desc()).limit(limit * 2) # Overfetch to allow Python-side tier filtering
        
        result = await db.execute(stmt)
        reports = result.scalars().all()
        
        # 2. Python-side Failsafe & Tier Filtering
        filtered_reports = []
        for r in reports:
            r_type = (r.report_type or "").lower()
            t_code = (r.topic_code or "").lower()
            r_plan = r.plan_required or "free"
            
            # Filter system reports
            if "system" in r_type or "diagnostic" in r_type or t_code == "system":
                continue
                
            # Tier Gating (Strict)
            if not is_tier_sufficient(tier, r_plan) and user.user_role != "admin":
                continue

            filtered_reports.append(r)

        # Final limit application after tier filtering
        final_reports = filtered_reports[:limit]

        return [
            {
                "id": str(r.id),
                "report_type": r.report_type or "unknown",
                "topic_code": r.topic_code or "global",
                "is_premium": bool(r.is_premium),
                "plan_required": r.plan_required or "free",
                "source_count": r.source_count or 0,
                "confidence_level": r.confidence_level or "Low",
                "created_at": r.created_at.isoformat() if hasattr(r.created_at, 'isoformat') else str(r.created_at),
                "content_markdown": (r.content_markdown or "")[:300] + "...",
                "title": r.title or f"{r.topic_code} Briefing",
                "teaser_md": r.teaser_md
            } for r in final_reports
        ]
    except Exception as e:
        import traceback
        with open("tmp/api_error.log", "a") as f:
            f.write(f"\n--- ERROR at {datetime.now(timezone.utc)} ---\n")
            f.write(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

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
        "is_premium": report.is_premium,
        "source_count": report.source_count,
        "confidence_level": report.confidence_level,
        "created_at": report.created_at.isoformat() if hasattr(report.created_at, 'isoformat') else report.created_at
    }

@app.post("/api/analytics/event")
async def log_analytics_event(
    event: AnalyticsEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[AnalystProfile] = Depends(get_optional_current_user)
):
    """Log an analytics event (preview_view, cta_click, full_view, etc.)"""
    # Permission check: unauthenticated can only log preview_view and cta_click
    allowed_unauth = ["preview_view", "cta_click", "checkout_flow"]
    if not current_user and event.event_type not in allowed_unauth:
        raise HTTPException(status_code=403, detail="Unauthenticated users can only log preview and CTA events")

    # If auth exists but the dependency returned a tuple (AnalystProfile, session_id, version), extract profile
    user_obj = None
    if current_user:
        # Check if it's a tuple (from some dependencies) or a direct profile
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
    
@app.get("/api/system/diagnostics")
async def get_system_diagnostics(
    current_user: tuple = Depends(get_current_user_from_access),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve diagnostic reports for internal debugging (Admin only)."""
    user, _, _ = current_user
    if user.user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
        
    stmt = select(Report).where(Report.report_type == "system_diagnostic").order_by(Report.created_at.desc()).limit(10)
    results = (await db.execute(stmt)).scalars().all()
    
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "content": r.content_markdown,
            "created_at": r.created_at.isoformat() if hasattr(r.created_at, 'isoformat') else r.created_at
        } for r in results
    ]

# --- Static File Serving (Moved to bottom) ---
# NOTE: In production on Render, these should be served from the 'web_dashboard/dist' folder.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dist_path = os.path.join(BASE_DIR, "web_dashboard", "dist")

logger.info(f"Looking for static files at: {dist_path}")
if os.path.exists(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")
else:
    logger.warning(f"Static files directory not found: {dist_path}")
    logger.warning(f"Contents of {BASE_DIR}: {os.listdir(BASE_DIR) if os.path.exists(BASE_DIR) else 'N/A'}")
    web_dashboard_dir = os.path.join(BASE_DIR, "web_dashboard")
    logger.warning(f"Contents of {web_dashboard_dir}: {os.listdir(web_dashboard_dir) if os.path.exists(web_dashboard_dir) else 'N/A'}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
