import asyncio
import uuid
import json
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import AnalystProfile
from api.auth import verify_password, create_access_token, create_refresh_token, session_manager
from api.auth_session import SecurityLogger

async def test_login():
    chat_id = "stripe_tester"
    password = "password123"
    
    print(f"Testing login for {chat_id}...")
    async with AsyncSessionLocal() as db:
        try:
            # 1. Fetch User
            stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == chat_id)
            user = (await db.execute(stmt)).scalar_one_or_none()
            
            if not user:
                print("FAILURE: User not found")
                return
                
            print(f"User found: {user.id}")
            
            # 2. Verify Password
            if not verify_password(password, user.hashed_password):
                print("FAILURE: Invalid password")
                return
            
            print("Password verified.")
            
            # 3. Create Session
            session_id = await session_manager.create_session(db, user.id)
            print(f"Session created: {session_id}")
            
            # 4. Create Tokens
            version = 1
            access_token = create_access_token({"sub": str(user.id), "session_id": str(session_id), "v": version})
            refresh_token, jti = create_refresh_token(user.id, session_id, version)
            print("Tokens generated.")
            
            # 5. Log Security Event
            await SecurityLogger.log_event(db, "login_success", user_id=user.id, session_id=session_id, client_ip="127.0.0.1")
            print("Security event logged.")
            
            print("SUCCESS: Login logic fully executed.")
            
        except Exception as e:
            print(f"EXCEPTION: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_login())
