import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AlertLog
from sqlalchemy import select
from jobs.pro_brief_trigger_policy import should_generate_pro_brief

async def diagnose_specific_alerts():
    ids = [
        'b0f36726-6ec1-4d85-820e-be9c804ab5ab', 
        '9723a998-370e-403f-915e-8325f83f80df'
    ]
    async with AsyncSessionLocal() as db:
        for id_ in ids:
            stmt = select(AlertLog).where(AlertLog.id == uuid.UUID(id_))
            alert = (await db.execute(stmt)).scalar()
            if alert:
                should_gen, reasons, diag = await should_generate_pro_brief(db, alert)
                print(f"\nAlert: {alert.topic} ({id_})")
                print(f"Should Generate: {should_gen}")
                print(f"Reasons: {reasons}")
                print(f"Diagnostics: {diag}")
            else:
                print(f"Alert {id_} not found")

if __name__ == "__main__":
    asyncio.run(diagnose_specific_alerts())
