import os
os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://mock"
os.environ["SECRET_KEY"] = "test_secret"

import pytest
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from api.main import app
from db.database import Base, engine, AsyncSessionLocal
from db.models import AnalystProfile, AlertLog
from api.auth import create_access_token
from api.gating import TIER_FREE, TIER_PRO, TIER_ENTERPRISE

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

# Basic Mock for Rate Limiter Redis
class MockRedis:
    def __init__(self):
        self.data = {}
        
    async def get(self, key):
        return self.data.get(key)
        
    def pipeline(self):
        return self

    async def incr(self, key):
        self.data[key] = int(self.data.get(key, 0)) + 1
        
    async def expire(self, key, seconds):
        pass

    async def execute(self):
        pass

import pytest_asyncio

# Initialize DB
@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture(autouse=True)
def mock_redis_modules(monkeypatch):
    import api.rate_limit
    import api.auth
    mock_redis = MockRedis()
    
    async def mock_is_available(*args, **kwargs):
        return True
        
    monkeypatch.setattr(api.rate_limit.limiter, "redis", mock_redis)
    monkeypatch.setattr(api.auth.blacklist_manager, "redis_client", mock_redis)
    monkeypatch.setattr(api.auth.blacklist_manager, "_is_redis_available", mock_is_available)

def get_token(user_id: uuid.UUID):
    session_id = uuid.uuid4()
    return create_access_token({"sub": str(user_id), "session_id": str(session_id), "v": 1})

@pytest.mark.asyncio
async def test_tiered_rate_limiting():
    async with AsyncSessionLocal() as db:
        user_free = AnalystProfile(telegram_chat_id="free1", subscription_tier=TIER_FREE)
        user_pro = AnalystProfile(telegram_chat_id="pro1", subscription_tier=TIER_PRO)
        db.add_all([user_free, user_pro])
        await db.commit()

        token_free = get_token(user_free.id)
        token_pro = get_token(user_pro.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # TIER_FREE max 20 per minute on /api/alerts
        for _ in range(20):
            res = await client.get("/api/alerts", headers={"Authorization": f"Bearer {token_free}"})
            assert res.status_code == 200
            
        # 21st should fail
        res = await client.get("/api/alerts", headers={"Authorization": f"Bearer {token_free}"})
        assert res.status_code == 429
        
        # TIER_PRO should succeed (limit 100)
        res = await client.get("/api/alerts", headers={"Authorization": f"Bearer {token_pro}"})
        assert res.status_code == 200

@pytest.mark.asyncio
async def test_expiration_and_grace_period():
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        # Expired 1 day ago (in 3-day grace period)
        user_grace = AnalystProfile(
            telegram_chat_id="grace1", 
            subscription_tier=TIER_PRO, 
            subscription_expires_at=now - timedelta(days=1)
        )
        # Expired 4 days ago (outside grace period)
        user_expired = AnalystProfile(
            telegram_chat_id="expired1", 
            subscription_tier=TIER_PRO, 
            subscription_expires_at=now - timedelta(days=4)
        )
        db.add_all([user_grace, user_expired])
        await db.commit()

    from api.gating import get_effective_tier
    
    # Grace user retains PRO tier
    assert await get_effective_tier(user_grace) == TIER_PRO
    
    # Expired user falls back to FREE tier
    assert await get_effective_tier(user_expired) == TIER_FREE

@pytest.mark.asyncio
async def test_split_metrics():
    async with AsyncSessionLocal() as db:
        admin_user = AnalystProfile(telegram_chat_id="admin1", user_role="admin", subscription_tier=TIER_PRO)
        analyst_user = AnalystProfile(telegram_chat_id="analyst1", user_role="analyst", subscription_tier=TIER_PRO)
        db.add_all([admin_user, analyst_user])
        await db.commit()
        
        token_admin = get_token(admin_user.id)
        token_analyst = get_token(analyst_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Analyst metrics (summary only)
        res_a = await client.get("/api/system/metrics", headers={"Authorization": f"Bearer {token_analyst}"})
        assert res_a.status_code == 200, res_a.text
        assert "status_summary" in res_a.json()
        assert "top_performing_triggers" not in res_a.json()
        
        # Admin metrics (full details)
        res_admin = await client.get("/api/system/metrics", headers={"Authorization": f"Bearer {token_admin}"})
        assert res_admin.status_code == 200, res_admin.text
        assert "top_performing_triggers" in res_admin.json()
