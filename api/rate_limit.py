import time
import logging
from typing import Dict, Tuple
from fastapi import HTTPException, Request, Depends
from api.auth import blacklist_manager
from api.gating import get_effective_tier, TIER_GUEST, TIER_FREE, TIER_PRO, TIER_ENTERPRISE
from api.auth import get_current_user_from_access, get_optional_current_user

logger = logging.getLogger(__name__)

# Limits: (count, period_seconds)
# Default limits if not specified
DEFAULT_LIMITS = {
    TIER_GUEST: (50, 3600), # 50/hr for Guests
    TIER_FREE: (50, 3600),
    TIER_PRO: (1000, 3600), # 1000/hr
    TIER_ENTERPRISE: (10000, 3600) 
}

# Endpoint specific limits
ENDPOINT_LIMITS: Dict[str, Dict[str, Tuple[int, int]]] = {
    "/api/alerts": {
        TIER_GUEST: (5, 60), # 5/min for Guests
        TIER_FREE: (5, 60),
        TIER_PRO: (100, 60),
        TIER_ENTERPRISE: (500, 60)
    },
    "/api/system/health": {
        TIER_GUEST: (2, 60),
        TIER_FREE: (5, 60),
        TIER_PRO: (20, 60),
        TIER_ENTERPRISE: (100, 60)
    }
}

class RateLimiter:
    def __init__(self, redis_client):
        self.redis = redis_client

    async def is_over_limit(self, user_id: str, endpoint: str, tier: str) -> bool:
        """Check if user is over their rate limit for a specific endpoint/tier."""
        if not await blacklist_manager._is_redis_available():
            return False # Fail open in dev/memory mode or if Redis is down
            
        limit, period = ENDPOINT_LIMITS.get(endpoint, {}).get(tier, DEFAULT_LIMITS.get(tier, DEFAULT_LIMITS[TIER_FREE]))
        
        key = f"rl:{user_id}:{endpoint}"
        try:
            current = await self.redis.get(key)
            if current and int(current) >= limit:
                return True
                
            # Increment and set TTL if new
            pipe = self.redis.pipeline()
            await pipe.incr(key)
            await pipe.expire(key, period)
            await pipe.execute()
            return False
        except Exception as e:
            logger.error(f"Rate limiter error: {e}")
            return False

limiter = RateLimiter(blacklist_manager.redis_client)

def rate_limit(endpoint: str = None):
    """FastAPI decorator for tiered rate limiting. Supports Guests via IP."""
    async def rate_limit_checker(
        request: Request,
        current_user: Optional[tuple] = Depends(get_optional_current_user)
    ):
        # current_user is (user, session_id, version) or None
        user = current_user[0] if current_user else None
        
        if user:
            user_id = str(user.id)
            tier = await get_effective_tier(user)
        else:
            # Fallback to IP for Guests
            user_id = f"ip:{request.client.host}"
            tier = TIER_GUEST

        path = endpoint or request.url.path
        
        if await limiter.is_over_limit(user_id, path, tier):
            raise HTTPException(
                status_code=429, 
                detail="Rate limit exceeded. Please sign in or upgrade for higher capacity."
            )
        return user
    return rate_limit_checker
