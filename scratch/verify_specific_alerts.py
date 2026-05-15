import asyncio
import sys
import os
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AlertLog
from jobs.pro_brief_trigger_policy import should_generate_pro_brief
from sqlalchemy import select

async def verify_alerts():
    target_ids = [
        "b0f36726-6ec1-4d85-820e-be9c804ab5ab", # Global Market
        "9723a998-5c7a-4b9e-8e2d-3c4a1b2d3e4f"  # Supply Chain (Guessing the full ID from prefix)
    ]
    
    async with AsyncSessionLocal() as db:
        print("=" * 80)
        print("VERIFYING SPECIFIC ALERTS")
        print("=" * 80)
        
        for tid in target_ids:
            # Try to find by prefix if not exact
            from sqlalchemy import String, cast
            stmt = select(AlertLog).where(cast(AlertLog.id, String).like(f"{tid[:8]}%"))
            res = await db.execute(stmt)
            alert = res.scalar_one_or_none()
            
            if not alert:
                print(f"\n[NOT FOUND] Alert starting with {tid[:8]}")
                continue
                
            print(f"\n[CHECKING] Alert {alert.id} ({alert.topic})")
            print(f"  Severity: {alert.severity} | Fidelity: {alert.fidelity_score} | Intelligence: {alert.intelligence_score}")
            
            should_gen, reasons, diag = await should_generate_pro_brief(db, alert)
            print(f"  Should Generate: {should_gen}")
            print(f"  Reasons: {reasons}")
            print(f"  Diagnostics: {diag}")

if __name__ == "__main__":
    asyncio.run(verify_alerts())
