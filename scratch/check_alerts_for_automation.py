import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AlertLog, Report
from sqlalchemy import select, desc, func

async def check_alerts():
    async with AsyncSessionLocal() as db:
        print("Recent Alerts:")
        stmt = select(AlertLog).order_by(desc(AlertLog.triggered_at)).limit(10)
        res = await db.execute(stmt)
        alerts = res.scalars().all()
        for a in alerts:
            print(f"ID: {a.id} | Topic: {a.topic} | Severity: {a.severity} | Fid: {a.fidelity_score} | Time: {a.triggered_at}")
            
        print("\nExisting Pro Reports (last 24h):")
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(hours=24)
        stmt = select(Report).where(
            Report.plan_required == "pro",
            Report.created_at >= yesterday
        )
        res = await db.execute(stmt)
        reports = res.scalars().all()
        for r in reports:
            print(f"ID: {r.id} | Topic: {r.topic_code} | Title: {r.title}")

if __name__ == "__main__":
    asyncio.run(check_alerts())
