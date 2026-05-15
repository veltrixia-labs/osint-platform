import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AlertLog
from sqlalchemy import select
import uuid

async def check_alerts():
    ids = [
        'b0f36726-6ec1-4d85-820e-be9c804ab5ab', 
        '9723a998-370e-403f-915e-8325f83f80df'
    ]
    async with AsyncSessionLocal() as db:
        print(f"Current UTC: {datetime.now(timezone.utc)}")
        for id_ in ids:
            stmt = select(AlertLog).where(AlertLog.id == uuid.UUID(id_))
            a = (await db.execute(stmt)).scalar()
            if a:
                print(f"{id_}: {a.topic} | {a.triggered_at} | Suppressed: {a.suppressed}")
            else:
                print(f"{id_}: Not found")

if __name__ == "__main__":
    asyncio.run(check_alerts())
