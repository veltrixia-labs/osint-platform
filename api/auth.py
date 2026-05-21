import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Any
from jose import JWTError, jwt
from argon2 import PasswordHasher
from fastapi import Request, Response, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db
from db.models import AnalystProfile
from api.auth_session import BlacklistManager, SessionManager, SecurityLogger

# Secret configuration (Should be in .env)
# Prefer JWT_SECRET_KEY in production; keep SECRET_KEY as backward-compatible fallback.
SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY", "osint-super-secret-dev-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7

ph = PasswordHasher()
blacklist_manager = BlacklistManager(os.getenv("REDIS_URL"))
session_manager = SessionManager(blacklist_manager)

def get_password_hash(password: str) -> str:
    return ph.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password)
    except:
        return False

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "jti": str(uuid.uuid4()), "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(user_id: uuid.UUID, session_id: uuid.UUID, version: int, parent_jti: Optional[str] = None):
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    jti = str(uuid.uuid4())
    to_encode = {
        "sub": str(user_id),
        "session_id": str(session_id),
        "v": version,
        "parent_jti": parent_jti,
        "jti": jti,
        "exp": expire,
        "type": "refresh"
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM), jti

from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

async def get_current_user_from_access(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        session_id: str = payload.get("session_id")
        version: int = payload.get("v")
        token_type: str = payload.get("type")
        
        if user_id is None or token_type != "access" or session_id is None:
            raise credentials_exception
            
        # Revocation check (includes version check)
        if await session_manager.validate_session(db, uuid.UUID(session_id), version) is False:
            raise credentials_exception
            
        stmt = select(AnalystProfile).where(AnalystProfile.id == uuid.UUID(user_id))
        user = (await db.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise credentials_exception
        return user, uuid.UUID(session_id), version
    except JWTError:
        raise credentials_exception

def resolve_optional_user(
    current_user: Optional[AnalystProfile] | tuple | Any,
) -> Optional[AnalystProfile]:
    """Normalize Depends output: optional user profile or (user, session_id, version) tuple."""
    if current_user is None:
        return None
    if isinstance(current_user, tuple):
        return current_user[0] if current_user else None
    return current_user


async def get_optional_current_user(token: Optional[str] = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> Optional[AnalystProfile]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        session_id: str = payload.get("session_id")
        version: int = payload.get("v")
        if not user_id or not session_id:
            return None
            
        if await session_manager.validate_session(db, uuid.UUID(session_id), version) is False:
            return None

        stmt = select(AnalystProfile).where(AnalystProfile.id == uuid.UUID(user_id))
        return (await db.execute(stmt)).scalar_one_or_none()
    except:
        return None

async def refresh_tokens(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")
    
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        session_id: str = payload.get("session_id")
        version: int = payload.get("v")
        jti: str = payload.get("jti")
        parent_jti: str = payload.get("parent_jti")
        token_type: str = payload.get("type")

        if token_type != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

        # 1. Chain Revocation Check
        if not await session_manager.validate_session(db, uuid.UUID(session_id), version):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")

        # 2. Rotation Logic (Custom check for JTI reuse)
        if await blacklist_manager._is_redis_available():
            old_child = await blacklist_manager.redis_client.get(f"jti_parent:{jti}")
            if old_child:
                # REUSE DETECTED!
                await session_manager.handle_reuse_detection(db, uuid.UUID(session_id), uuid.UUID(user_id), jti, request.client.host)
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Security breach: session revoked")

        # Generate new pair
        new_access = create_access_token({"sub": user_id, "session_id": session_id, "v": version})
        new_refresh, new_jti = create_refresh_token(uuid.UUID(user_id), uuid.UUID(session_id), version, jti)

        # 3. Mark old JTI as used
        if await blacklist_manager._is_redis_available():
            await blacklist_manager.redis_client.setex(f"jti_parent:{jti}", 86400 * 7, new_jti)

        # Set cookie
        response.set_cookie(
            key="refresh_token",
            value=new_refresh,
            httponly=True,
            secure=os.getenv("ENV") == "production",
            samesite="lax",
            path="/api/auth",
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400
        )
        return {"access_token": new_access, "token_type": "bearer"}

    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
