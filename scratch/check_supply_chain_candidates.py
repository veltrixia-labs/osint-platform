import asyncio
import sys
import os
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AlertLog, Report
from jobs.pro_brief_trigger_policy import should_generate_pro_brief
from sqlalchemy import select, desc

async def check_supply_chain_candidates():
    topic = "supply_chain_intelligence"
    async with AsyncSessionLocal() as db:
        print("=" * 80)
        print(f"DIAGNOSING CANDIDATES FOR: {topic}")
        print("=" * 80)
        
        # Get latest alerts for this topic
        stmt = select(AlertLog).where(AlertLog.topic == topic).order_by(desc(AlertLog.triggered_at)).limit(5)
        res = await db.execute(stmt)
        alerts = res.scalars().all()
        
        if not alerts:
            print("No alerts found for this topic.")
            return
            
        for alert in alerts:
            should_gen, reasons, diag = await should_generate_pro_brief(db, alert)
            print(f"\n[ALERT] {alert.id} ({alert.target_label})")
            print(f"  Fidelity: {alert.fidelity_score} | Intelligence: {alert.intelligence_score}")
            print(f"  Should Generate: {should_gen}")
            print(f"  Reasons: {reasons}")
            print(f"  Diagnostics: {diag}")

if __name__ == "__main__":
    asyncio.run(check_supply_chain_candidates())
