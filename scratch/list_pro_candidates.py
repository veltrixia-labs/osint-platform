import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.database import AsyncSessionLocal
from sqlalchemy import select, desc
from db.models import AlertLog
from analysis.pro_domain_config import PRO_DOMAIN_CONFIG

async def list_candidates():
    valid_topics = list(PRO_DOMAIN_CONFIG.keys())
    async with AsyncSessionLocal() as db:
        stmt = select(AlertLog).where(
            AlertLog.topic.in_(valid_topics)
        ).order_by(desc(AlertLog.triggered_at)).limit(20)
        
        res = await db.execute(stmt)
        alerts = res.scalars().all()
        
        print(f"{'ID':<38} | {'TOPIC':<30} | {'TARGET':<30} | {'SEV':<8} | {'INT':<5} | {'FID':<5} | {'EV':<3} | {'TRIGGERED_AT'}")
        print("-" * 150)
        for a in alerts:
            print(f"{str(a.id):<38} | {str(a.topic):<30} | {str(a.target_label):<30} | {str(a.severity):<8} | {str(a.intelligence_score):<5} | {str(a.fidelity_score):<5} | {str(a.supporting_events_count):<3} | {a.triggered_at}")

if __name__ == "__main__":
    asyncio.run(list_candidates())
