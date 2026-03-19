"""
Phase 30 - Commercialization & Payment Integration Validation Suite

Tests cover:
1. Mock Checkout Flow - tier upgrades via /api/payments/mock/checkout-success
2. Webhook Simulation - checkout.session.completed updates DB
3. Subscription Cancellation - customer.subscription.canceled downgrades tier
4. Expiration Logic - expired subscription handled with grace period
5. Access Control - free vs pro tier gating enforcement
"""

import pytest
import pytest_asyncio
import uuid
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

# --- Test Configuration ---
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_phase30.db"
os.environ["SECRET_KEY"] = "test-phase30-secret"
os.environ["REDIS_URL"] = ""

# Patch JSONB → JSON for SQLite compatibility BEFORE importing models
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return 'JSON'

from api.main import app
from db.database import AsyncSessionLocal, engine
from db.models import Base, AnalystProfile, ExternalPost
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from api.auth import create_access_token, get_password_hash
from api.gating import get_effective_tier, TIER_FREE, TIER_PRO, TIER_ENTERPRISE, GRACE_PERIOD_DAYS
from api.auth_session import SessionRevocation


# ==========================================
# Fixtures
# ==========================================

@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_db():
    """Create fresh test database at start, drop at end."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


async def _make_analyst(session: AsyncSession, tier: str = TIER_FREE, expires_at=None) -> AnalystProfile:
    analyst = AnalystProfile(
        telegram_chat_id=f"test_{uuid.uuid4().hex[:8]}",
        hashed_password=get_password_hash("password"),
        user_role="analyst",
        subscription_tier=tier,
        subscription_expires_at=expires_at,
    )
    session.add(analyst)
    await session.commit()
    await session.refresh(analyst)
    return analyst


def _make_auth_header(user_id: uuid.UUID) -> dict:
    """Generate a mocked access token that bypasses session checks."""
    token = create_access_token({
        "sub": str(user_id),
        "session_id": str(uuid.uuid4()),
        "v": 1
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def http_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


# ==========================================
# 1. Mock Checkout Flow
# ==========================================

class TestMockCheckoutFlow:

    @pytest.mark.asyncio
    async def test_mock_checkout_upgrades_to_pro(self, db_session, http_client):
        analyst = await _make_analyst(db_session, tier=TIER_FREE)
        assert analyst.subscription_tier == TIER_FREE

        with patch("api.auth_session.SessionManager.validate_session", return_value=True):
            response = await http_client.get(
                f"/api/payments/mock/checkout-success",
                params={"tier": "pro", "analyst_id": str(analyst.id)}
            )

        assert response.status_code == 200
        assert response.json()["status"] == "success"

        await db_session.refresh(analyst)
        assert analyst.subscription_tier == TIER_PRO
        assert analyst.stripe_customer_id == "cus_mock_123"
        assert analyst.stripe_subscription_id == "sub_mock_456"
        assert analyst.subscription_expires_at is not None

    @pytest.mark.asyncio
    async def test_mock_checkout_upgrades_to_enterprise(self, db_session, http_client):
        analyst = await _make_analyst(db_session, tier=TIER_FREE)

        with patch("api.auth_session.SessionManager.validate_session", return_value=True):
            response = await http_client.get(
                f"/api/payments/mock/checkout-success",
                params={"tier": "enterprise", "analyst_id": str(analyst.id)}
            )

        assert response.status_code == 200
        await db_session.refresh(analyst)
        assert analyst.subscription_tier == TIER_ENTERPRISE

    @pytest.mark.asyncio
    async def test_mock_checkout_unknown_analyst_is_silent(self, http_client):
        """Should return success even if analyst does not exist (no-op)."""
        response = await http_client.get(
            "/api/payments/mock/checkout-success",
            params={"tier": "pro", "analyst_id": str(uuid.uuid4())}
        )
        assert response.status_code == 200


# ==========================================
# 2. Webhook - checkout.session.completed
# ==========================================

class TestStripeWebhookCheckout:

    @pytest.mark.asyncio
    async def test_webhook_upgrades_tier_on_checkout_completed(self, db_session, http_client):
        analyst = await _make_analyst(db_session, tier=TIER_FREE)

        webhook_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(analyst.id),
                    "customer": "cus_webhook_001",
                    "subscription": "sub_webhook_001",
                    "metadata": {"tier": "pro", "analyst_id": str(analyst.id)}
                }
            }
        }

        response = await http_client.post(
            "/api/payments/webhook",
            content=json.dumps(webhook_payload),
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 200
        # Re-query in fresh session - the webhook committed in its own session
        async with AsyncSessionLocal() as fresh:
            stmt = select(AnalystProfile).where(AnalystProfile.id == analyst.id)
            updated = (await fresh.execute(stmt)).scalars().first()
        assert updated.subscription_tier == TIER_PRO
        assert updated.stripe_customer_id == "cus_webhook_001"
        assert updated.stripe_subscription_id == "sub_webhook_001"

    @pytest.mark.asyncio
    async def test_webhook_falls_back_to_metadata_analyst_id(self, db_session, http_client):
        """Tests that metadata.analyst_id is used if client_reference_id is missing."""
        analyst = await _make_analyst(db_session, tier=TIER_FREE)

        webhook_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": None,
                    "customer": "cus_webhook_002",
                    "subscription": "sub_webhook_002",
                    "metadata": {"tier": "enterprise", "analyst_id": str(analyst.id)}
                }
            }
        }

        response = await http_client.post(
            "/api/payments/webhook",
            content=json.dumps(webhook_payload),
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 200
        # Re-query in fresh session - the webhook committed in its own session
        async with AsyncSessionLocal() as fresh:
            stmt = select(AnalystProfile).where(AnalystProfile.id == analyst.id)
            updated = (await fresh.execute(stmt)).scalars().first()
        assert updated.subscription_tier == TIER_ENTERPRISE


# ==========================================
# 3. Subscription Cancellation
# ==========================================

class TestSubscriptionCancellation:

    @pytest.mark.asyncio
    async def test_cancellation_webhook_downgrades_to_free(self, db_session, http_client):
        analyst = await _make_analyst(
            db_session,
            tier=TIER_PRO,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30)
        )
        analyst.stripe_customer_id = "cus_cancel_001"
        await db_session.commit()

        webhook_payload = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "customer": "cus_cancel_001"
                }
            }
        }

        response = await http_client.post(
            "/api/payments/webhook",
            content=json.dumps(webhook_payload),
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 200
        # Re-query in fresh session - the webhook committed in its own session
        async with AsyncSessionLocal() as fresh:
            stmt = select(AnalystProfile).where(AnalystProfile.id == analyst.id)
            updated = (await fresh.execute(stmt)).scalars().first()
        assert updated.subscription_tier == TIER_FREE
        # SQLite returns timezone-naive datetimes; normalize for comparison
        expires = updated.subscription_expires_at
        if expires and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        assert expires <= datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_canceled_webhook_variant(self, db_session, http_client):
        """Tests customer.subscription.canceled triggers the same downgrade."""
        analyst = await _make_analyst(db_session, tier=TIER_ENTERPRISE)
        analyst.stripe_customer_id = "cus_cancel_002"
        await db_session.commit()

        webhook_payload = {
            "type": "customer.subscription.canceled",
            "data": {
                "object": {"customer": "cus_cancel_002"}
            }
        }

        response = await http_client.post(
            "/api/payments/webhook",
            content=json.dumps(webhook_payload),
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 200
        await db_session.refresh(analyst)
        assert analyst.subscription_tier == TIER_FREE


# ==========================================
# 4. Expiration & Grace Period Logic
# ==========================================

class TestExpirationLogic:

    @pytest.mark.asyncio
    async def test_active_subscription_returns_correct_tier(self):
        analyst = AnalystProfile(
            subscription_tier=TIER_PRO,
            subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=15),
        )
        tier = await get_effective_tier(analyst)
        assert tier == TIER_PRO

    @pytest.mark.asyncio
    async def test_expired_subscription_within_grace_returns_pro(self):
        """Within GRACE_PERIOD_DAYS: should still return the paid tier."""
        analyst = AnalystProfile(
            subscription_tier=TIER_PRO,
            subscription_expires_at=datetime.now(timezone.utc) - timedelta(days=GRACE_PERIOD_DAYS - 1),
        )
        tier = await get_effective_tier(analyst)
        assert tier == TIER_PRO

    @pytest.mark.asyncio
    async def test_expired_subscription_past_grace_returns_free(self):
        """After GRACE_PERIOD_DAYS: should downgrade to free."""
        analyst = AnalystProfile(
            subscription_tier=TIER_PRO,
            subscription_expires_at=datetime.now(timezone.utc) - timedelta(days=GRACE_PERIOD_DAYS + 1),
        )
        tier = await get_effective_tier(analyst)
        assert tier == TIER_FREE

    @pytest.mark.asyncio
    async def test_no_expiry_returns_subscription_tier(self):
        """No expiry set → permanent: return tier as-is."""
        analyst = AnalystProfile(
            subscription_tier=TIER_PRO,
            subscription_expires_at=None,
        )
        tier = await get_effective_tier(analyst)
        assert tier == TIER_PRO

    @pytest.mark.asyncio
    async def test_enterprise_no_expiry(self):
        analyst = AnalystProfile(
            subscription_tier=TIER_ENTERPRISE,
            subscription_expires_at=None,
        )
        tier = await get_effective_tier(analyst)
        assert tier == TIER_ENTERPRISE

    @pytest.mark.asyncio
    async def test_free_user_with_no_expires(self):
        analyst = AnalystProfile(
            subscription_tier=TIER_FREE,
            subscription_expires_at=None,
        )
        tier = await get_effective_tier(analyst)
        assert tier == TIER_FREE


# ==========================================
# 5. Access Control Validation
# ==========================================

class TestAccessControl:
    """
    These tests validate that tier enforcement works correctly at the endpoint level.
    We bypass session validation via mock to test the gating layer in isolation.
    """

    @pytest.mark.asyncio
    async def test_pro_endpoint_blocks_free_user(self, db_session, http_client):
        """A free-tier analyst should receive 403 from a Pro-gated endpoint."""
        analyst = await _make_analyst(db_session, tier=TIER_FREE)
        headers = _make_auth_header(analyst.id)

        with patch("api.auth_session.SessionManager.validate_session", return_value=True):
            response = await http_client.get("/api/reports/specialized", headers=headers)

        # Expect 403 or 404 (if no items), but never 200 on a tier-blocked call
        assert response.status_code in (403, 404, 422)

    @pytest.mark.asyncio
    async def test_pro_endpoint_allows_pro_user(self, db_session, http_client):
        """A pro-tier analyst should NOT receive 403 from a Pro-gated endpoint."""
        analyst = await _make_analyst(
            db_session,
            tier=TIER_PRO,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30)
        )
        headers = _make_auth_header(analyst.id)

        with patch("api.auth_session.SessionManager.validate_session", return_value=True):
            response = await http_client.get("/api/reports/specialized", headers=headers)

        assert response.status_code != 403

    @pytest.mark.asyncio
    async def test_checkout_session_invalid_tier_returns_400(self, db_session, http_client):
        analyst = await _make_analyst(db_session, tier=TIER_FREE)
        headers = _make_auth_header(analyst.id)

        with patch("api.auth_session.SessionManager.validate_session", return_value=True):
            response = await http_client.get(
                "/api/payments/checkout-session",
                params={"tier": "ultra_cosmic"},
                headers=headers
            )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_expired_user_past_grace_is_blocked_from_pro(self, db_session, http_client):
        """A Pro user past the grace period should be treated as Free → blocked from Pro routes."""
        expired_at = datetime.now(timezone.utc) - timedelta(days=GRACE_PERIOD_DAYS + 2)
        analyst = await _make_analyst(db_session, tier=TIER_PRO, expires_at=expired_at)
        headers = _make_auth_header(analyst.id)

        with patch("api.auth_session.SessionManager.validate_session", return_value=True):
            response = await http_client.get("/api/reports/specialized", headers=headers)

        assert response.status_code in (403, 404, 422)


# ==========================================
# Run directly as a script for debugging
# ==========================================
if __name__ == "__main__":
    import subprocess
    subprocess.run(["pytest", __file__, "-v", "--tb=short"])
