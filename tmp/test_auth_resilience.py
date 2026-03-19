import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from api.auth_session import BlacklistManager, SessionManager
from db.models import SessionRevocation

class MockRedis:
    def __init__(self):
        self.data = {}
        self.available = True

    async def ping(self):
        if not self.available:
            raise Exception("Redis down")
        return True

    async def get(self, key):
        if not self.available:
            raise Exception("Redis down")
        return self.data.get(key)

    async def setex(self, key, ttl, value):
        if not self.available:
            raise Exception("Redis down")
        self.data[key] = value

@pytest.mark.asyncio
async def test_session_chain_revocation_on_reuse():
    """Verify that using a parent JTI after a child is issued revokes the whole chain."""
    db = AsyncMock()
    mock_rev = MagicMock(spec=SessionRevocation)
    mock_rev.revoked = False
    mock_rev.version = 1
    
    # Setup mock to return an object with scalar_one_or_none method
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_rev
    db.execute.return_value = mock_result
    
    redis_mock = MockRedis()
    blacklist = BlacklistManager()
    blacklist.redis_client = redis_mock
    sm = SessionManager(blacklist)
    
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    jti_parent = "parent_jti_123"
    
    # 1. Simulate a "reuse" event in Redis
    redis_mock.data[f"jti_parent:{jti_parent}"] = "child_jti_456"
    
    # 2. Call handle_reuse_detection
    await sm.handle_reuse_detection(db, session_id, user_id, jti_parent, "127.0.0.1")
    
    # Verify: session is revoked in DB
    assert mock_rev.revoked is True
    assert mock_rev.version == 2
    # Verify: session is revoked in Redis
    assert redis_mock.data[f"session:{session_id}:revoked"] == "1"

@pytest.mark.asyncio
async def test_redis_fallback_and_recovery():
    """Verify system falls back to DB when Redis is down, then recovers."""
    db = AsyncMock()
    mock_rev = MagicMock(spec=SessionRevocation)
    mock_rev.revoked = False
    mock_rev.version = 1

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_rev
    db.execute.return_value = mock_result

    redis_mock = MockRedis()
    blacklist = BlacklistManager()
    blacklist.redis_client = redis_mock
    
    session_id = uuid.uuid4()
    
    # 1. Redis is UP
    assert await blacklist.is_revoked(db, session_id, 1) is False
    
    # 2. Redis goes DOWN
    redis_mock.available = False
    # Should check DB and return False (since mock_rev.revoked is False)
    assert await blacklist.is_revoked(db, session_id, 1) is False
    
    # 3. Revoke while Redis is DOWN
    await blacklist.revoke_session(db, session_id, "test_down", bump_version=True)
    assert mock_rev.revoked is True
    
    # 4. Check status (should be True because mock_rev.revoked is now True)
    assert await blacklist.is_revoked(db, session_id, 1) is True
    
    # 5. Redis comes back UP
    redis_mock.available = True
    # Still should be revoked (cached in memory or found in DB)
    assert await blacklist.is_revoked(db, session_id, 1) is True
