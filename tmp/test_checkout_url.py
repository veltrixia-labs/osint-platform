import sys
import os
import asyncio

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db.database import AsyncSessionLocal
from sqlalchemy.future import select
from db.models import AnalystProfile
from api.payments import create_checkout_session
import stripe
from config.settings import settings

stripe.api_key = settings.stripe_secret_key

async def test_checkout():
    async with AsyncSessionLocal() as db:
        stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == 'testuser')
        analyst = (await db.execute(stmt)).scalars().first()
        
        try:
            res = await create_checkout_session(
                tier="pro", 
                report_id="test_report_id", 
                return_url="http://localhost:5173",
                current_user=(analyst, None, None), 
                _rt=None, 
                db=db
            )
            session_id = res.get("session_id")
            
            # Use stripe sdk to retrieve the session and print success_url
            session = stripe.checkout.Session.retrieve(session_id)
            print("--- BACKEND TEST ---")
            print("SUCCESS_URL:", session.success_url)
            print("CANCEL_URL:", session.cancel_url)
        except Exception as e:
            print("ERROR:", e)

asyncio.run(test_checkout())
