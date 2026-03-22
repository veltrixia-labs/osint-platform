import sys
import os
import asyncio

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db.database import AsyncSessionLocal
from sqlalchemy.future import select
from db.models import AnalystProfile
from api.payments import create_checkout_session

async def test_checkout():
    async with AsyncSessionLocal() as db:
        stmt = select(AnalystProfile).where(AnalystProfile.telegram_chat_id == 'testuser')
        analyst = (await db.execute(stmt)).scalars().first()
        
        print("BEFORE: stripe_customer_id =", analyst.stripe_customer_id)
        
        try:
            res = await create_checkout_session("pro", report_id=None, current_user=(analyst, None, None), _rt=None, db=db)
            print("URL:", res.get("url") is not None)
            print("SESSION_ID:", res.get("session_id") is not None)
        except Exception as e:
            print("ERROR:", e)
            
        print("AFTER: stripe_customer_id =", analyst.stripe_customer_id)

asyncio.run(test_checkout())
