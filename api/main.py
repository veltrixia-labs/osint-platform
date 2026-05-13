"""
FastAPI application entrypoint.

Ensures the repository root is on ``sys.path`` so ``from api.routes...`` resolves
when the process cwd is not the repo root (e.g. some Render / container layouts).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_root_str = str(_ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)

from fastapi import FastAPI, HTTPException, Depends, Request, Response, status
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.future import select
from sqlalchemy import func
from db.models import AnalystProfile, Report, SystemMetric
from db.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
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
    TIER_PRO, TIER_EXPERTS, TIER_ORDER, is_tier_sufficient,
    is_topic_allowed, can_access_report_type, PlanTier
)
from db.enums import ReportType

# ── Feature Routers ────────────────────────────────────────────────────────────
from api.routes.alerts import router as alerts_router
from api.routes.reports import router as reports_router
from api.routes.analysts import router as analysts_router
from api.routes.system import router as system_router
from api.routes.analytics import router as analytics_router
from api.routes.insights import router as insights_router
from api.routes.backbone import router as backbone_router
from api.routes.free_feed import router as free_feed_router
from api.routes.pro_reports import router as pro_reports_router

# Production Traceability
COMMIT_HASH = "v11.1.2-AURORA-SYNC"
DEPLOY_TIMESTAMP = "2026-04-21T19:28:00Z"

app = FastAPI(title="OSINT Risk Analytics API")
logger = logging.getLogger(__name__)

# [Robustness] Startup Freshness & Seeding
def check_frontend_freshness():
    """Verify that built assets (dist) are newer than source code (src)."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src_path = os.path.join(base_dir, "web_dashboard", "src")
        dist_path = os.path.join(base_dir, "web_dashboard", "dist")

        if os.path.exists(src_path) and os.path.exists(dist_path):
            latest_src = 0
            for root, _, files in os.walk(src_path):
                for f in files:
                    mtime = os.path.getmtime(os.path.join(root, f))
                    if mtime > latest_src: latest_src = mtime

            latest_dist = os.path.getmtime(dist_path)
            for root, _, files in os.walk(dist_path):
                for f in files:
                    mtime = os.path.getmtime(os.path.join(root, f))
                    if mtime > latest_dist: latest_dist = mtime

            if latest_src > latest_dist:
                logger.warning(" [WARNING] Frontend assets are STALE. Src was modified after last Dist build.")
                logger.warning(" [ACTION REQUIRED] Run 'python scripts/setup_dev_env.py' to rebuild UI.")
        elif os.path.exists(src_path) and not os.path.exists(dist_path):
            # [v50] Suppress "ACTION REQUIRED" on Render Backend service
            if not os.getenv("RENDER"):
                logger.warning(" [WARNING] Frontend 'dist' folder is MISSING. API cannot serve UI.")
                logger.warning(" [ACTION REQUIRED] Run 'python scripts/setup_dev_env.py' to build UI.")
            else:
                logger.info("[Antigravity] Frontend 'dist' folder missing (Expected on Render Backend-only service).")
    except Exception as e:
        logger.error(f"Error checking frontend freshness: {e}")

@app.on_event("startup")
async def startup_event():
    try:
        from db.database import Base, AsyncSessionLocal, run_migrations
        from db.seeding import seed_admin

        # 1. Freshness Check
        check_frontend_freshness()

        # 2. Run Alembic Migrations
        run_migrations()
        logger.info("[Antigravity] Database migration/verification completed.")

        # 3. Seed Admin User
        async with AsyncSessionLocal() as session:
            await seed_admin(session)
        logger.info("[Antigravity] Startup initialization complete. Scheduler is running.")
    except Exception as e:
        logger.error(f"Error during API startup initialization: {e}", exc_info=True)


@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    """Prevent browser from caching stale UI assets in development."""
    response = await call_next(request)
    if os.getenv("DEBUG", "true").lower() == "true":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


logger.info("--- OSINT SCHEDULER STARTUP ---")
logger.info("SCHEDULER_V2_ACTIVE: SUCCESS_ASYNC_NATIVE")
logger.info(f"--- OSINT API BOOTING [Version: {COMMIT_HASH}] ---")

# ── Core Status Endpoints ──────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    return {"status": "ok", "message": "OSINT API is running", "version": COMMIT_HASH}

@app.get("/healthz")
async def healthz():
    return {"status": "healthy"}

@app.get("/api/health")
async def get_system_health(db: AsyncSession = Depends(get_db)):
    """Comprehensive health check for monitoring tools."""
    try:
        await db.execute(select(1))
        db_status = "connected"
    except Exception as e:
        db_status = f"unhealthy: {e}"

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

# Dynamic Whitelist + Production Authority (veltrixia.net apex + www).
# Extend via ALLOWED_ORIGINS (comma-separated). See also Render "Extra origins" if using preview URLs.
RAW_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://veltrixia.net",
    "https://www.veltrixia.net"
]
for r in RAW_ORIGINS:
    cleaned = r.strip().rstrip("/")
    if cleaned and cleaned not in ALLOWED_ORIGINS:
        ALLOWED_ORIGINS.append(cleaned)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

# ── Router Registration ────────────────────────────────────────────────────────
app.include_router(payments_router, prefix="/api/payments", tags=["payments"])
app.include_router(alerts_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(analysts_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(insights_router, prefix="/api")
app.include_router(backbone_router, prefix="/api")
app.include_router(free_feed_router, prefix="/api")
app.include_router(pro_reports_router, prefix="/api")

# ── Auth Endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
async def login(response: Response, request: Request, data: dict, db: AsyncSession = Depends(get_db)):
    email = data.get("email")
    password = data.get("password")

    logger.info(f"Login attempt for email: {email}")
    stmt = select(AnalystProfile).where(AnalystProfile.email == email)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user:
        logger.warning(f"Login failed: User not found for email: {email}")
        await SecurityLogger.log_event(db, "login_failed", details={"email": email, "reason": "user_not_found"}, client_ip=request.client.host)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(password, user.hashed_password):
        logger.warning(f"Login failed: Password mismatch for email: {email}")
        await SecurityLogger.log_event(db, "login_failed", details={"email": email, "reason": "password_mismatch"}, client_ip=request.client.host)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    session_id = await session_manager.create_session(db, user.id)
    version = 1

    access_token = create_access_token({"sub": str(user.id), "session_id": str(session_id), "v": version})
    refresh_token, jti = create_refresh_token(user.id, session_id, version)

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


class SignupData(BaseModel):
    email: str
    password: str
    telegram_chat_id: Optional[str] = None

@app.post("/api/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(request: Request, data: SignupData, db: AsyncSession = Depends(get_db)):
    email = data.email
    password = data.password
    chat_id = data.telegram_chat_id

    stmt = select(AnalystProfile).where(AnalystProfile.email == email)
    existing_user = (await db.execute(stmt)).scalar_one_or_none()

    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_pw = get_password_hash(password)
    new_user = AnalystProfile(
        id=uuid.uuid4(),
        email=email,
        telegram_chat_id=chat_id,
        hashed_password=hashed_pw,
        user_role="analyst",
        subscription_tier="free",
        is_active=True,
        created_at=datetime.now(timezone.utc)
    )

    db.add(new_user)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Signup failed for {email}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

    await SecurityLogger.log_event(db, "signup_success", user_id=new_user.id, details={"email": email}, client_ip=request.client.host)
    return {"status": "success", "message": "Account created successfully", "email": email}


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
    tier = await get_effective_tier(user)
    
    # Feature flags for UI conditional rendering
    features = {
        "pro_insights": is_tier_sufficient(tier, PlanTier.PRO.value),
        "expert_intelligence": is_tier_sufficient(tier, PlanTier.EXPERTS.value),
        "team_admin": tier == PlanTier.ENTERPRISE.value,
        "custom_topics": tier == PlanTier.ENTERPRISE.value,
        "onboarding": tier == PlanTier.ENTERPRISE.value,
        "support": tier == PlanTier.ENTERPRISE.value,
    }
    
    # Operational limits based on the tier specification
    impact_depth = 999 if is_tier_sufficient(tier, PlanTier.EXPERTS.value) else \
                   2 if is_tier_sufficient(tier, PlanTier.PRO.value) else 0
    
    # Derived lists of allowed data domains
    from api.gating import ALL_TOPIC_CODES
    allowed_topics = [t for t in ALL_TOPIC_CODES if is_topic_allowed(tier, t)]
    
    all_reports = ["daily", "weekly", "monthly", "system_diagnostic"]
    allowed_reports = [r for r in all_reports if can_access_report_type(tier, r)]

    return {
        "id": str(user.id),
        "email": user.email,
        "chat_id": user.telegram_chat_id,
        "role": user.user_role,
        "tier": tier,
        "expires_at": user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
        "features": features,
        "limits": {
            "impact_depth": impact_depth,
            "topics": allowed_topics,
            "reports": allowed_reports
        }
    }

# ── Static File Serving ────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
visuals_path = os.path.join(BASE_DIR, "outputs", "visuals")
archive_path = os.path.join(BASE_DIR, "outputs", "archive")
dist_path = os.path.join(BASE_DIR, "web_dashboard", "dist")

os.makedirs(visuals_path, exist_ok=True)
os.makedirs(archive_path, exist_ok=True)

app.mount("/visuals", StaticFiles(directory=visuals_path), name="visuals")
app.mount("/archive", StaticFiles(directory=archive_path), name="archive")

if os.path.exists(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
