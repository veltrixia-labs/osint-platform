import uuid
import json
import logging
from typing import Optional
import redis.asyncio as redis
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import SessionRevocation, SecurityLog
from datetime import datetime, timezone

# Configure application logging
logger = logging.getLogger("auth_session")

class BlacklistManager:
    """Manages token/session revocation with Redis -> DB -> Memory fallback."""
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_client = None
        if redis_url:
            try:
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                logger.info("AuthSession: Initialized Redis client for async tracking.")
            except Exception as e:
                logger.warning(f"AuthSession: Redis setup failed: {e}")
        
        self.local_cache = {} # Emergency memory mode

    async def _is_redis_available(self) -> bool:
        if not self.redis_client:
            return False
        try:
            await self.redis_client.ping()
            return True
        except:
            return False

    async def is_revoked(self, db: AsyncSession, session_id: uuid.UUID, version: int) -> bool:
        """Check if a session (or version) is revoked."""
        s_id = str(session_id)
        
        # 1. Try Redis
        if await self._is_redis_available():
            try:
                cached_v = await self.redis_client.get(f"session:{s_id}:v")
                if cached_v and int(cached_v) > version:
                    return True
                
                is_rev = await self.redis_client.get(f"session:{s_id}:revoked")
                if is_rev == "1":
                    return True
                
                # If we have a version but it's not bumped, and it's not revoked, 
                # we can return False IF we consider Redis as definitive for active sessions.
                # However, for safety, only return if we definitely found a state.
                if cached_v is not None:
                    return False 
            except Exception as e:
                logger.error(f"Redis error in is_revoked: {e}")

        # 2. Try Database (Primary Fallback)
        stmt = select(SessionRevocation).where(SessionRevocation.session_id == session_id)
        rev = (await db.execute(stmt)).scalar_one_or_none()
        if rev:
            if rev.revoked or rev.version > version:
                return True

        # 3. Try Local Cache (Emergency Mode)
        if s_id in self.local_cache:
            l_rev = self.local_cache[s_id]
            if l_rev.get("revoked") or l_rev.get("version", 1) > version:
                return True

        return False

    async def revoke_session(self, db: AsyncSession, session_id: uuid.UUID, reason: str, bump_version: bool = True):
        """Revoke an entire session chain."""
        s_id = str(session_id)
        now = datetime.now(timezone.utc)
        
        # 1. Update Database
        stmt = select(SessionRevocation).where(SessionRevocation.session_id == session_id)
        rev = (await db.execute(stmt)).scalar_one_or_none()
        if not rev:
            rev = SessionRevocation(session_id=session_id, version=1)
            db.add(rev)
        
        rev.revoked = True
        rev.revoked_at = now
        rev.reason = reason
        if bump_version:
            rev.version += 1
        await db.commit()

        # 2. Update Redis
        if await self._is_redis_available():
            try:
                await self.redis_client.setex(f"session:{s_id}:revoked", 86400 * 7, "1")
                await self.redis_client.setex(f"session:{s_id}:v", 86400 * 7, str(rev.version))
            except:
                pass

        # 3. Update Local Cache
        self.local_cache[s_id] = {"revoked": True, "version": rev.version}
        logger.warning(f"AuthSession: Session {s_id} revoked. Reason: {reason}")

class SecurityLogger:
    """Logs security events to DB and Application logs."""
    @staticmethod
    async def log_event(db: AsyncSession, event_type: str, user_id: Optional[uuid.UUID] = None, 
                        session_id: Optional[uuid.UUID] = None, details: dict = None, client_ip: str = None):
        
        log_msg = f"SECURITY EVENT [{event_type}] | User: {user_id} | Session: {session_id} | Details: {json.dumps(details)} | IP: {client_ip}"
        if event_type in ["token_reuse", "invalid_signature"]:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

        log_entry = SecurityLog(
            event_type=event_type,
            user_id=user_id,
            session_id=session_id,
            details=details,
            client_ip=client_ip
        )
        db.add(log_entry)
        await db.commit()

class SessionManager:
    """Orchestrates session lifecycle and chain tracking."""
    def __init__(self, blacklist_manager: BlacklistManager):
        self.blacklist = blacklist_manager

    async def create_session(self, db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
        session_id = uuid.uuid4()
        rev = SessionRevocation(session_id=session_id, version=1)
        db.add(rev)
        await db.commit()
        return session_id

    async def validate_session(self, db: AsyncSession, session_id: uuid.UUID, version: int) -> bool:
        return not await self.blacklist.is_revoked(db, session_id, version)

    async def handle_reuse_detection(self, db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID, faulty_jti: str, client_ip: str):
        reason = f"Refresh token reuse detected (JTI: {faulty_jti})"
        await self.blacklist.revoke_session(db, session_id, reason, bump_version=True)
        
        await SecurityLogger.log_event(
            db=db,
            event_type="token_reuse",
            user_id=user_id,
            session_id=session_id,
            details={"faulty_jti": faulty_jti, "action": "chain_revoked"},
            client_ip=client_ip
        )
