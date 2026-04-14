import asyncio
import json
from sqlalchemy import select, desc
from db.database import AsyncSessionLocal
from db.models import AlertLog

async def audit_pipeline():
    async with AsyncSessionLocal() as session:
        # Check last 10 alerts
        stmt = select(AlertLog).order_by(desc(AlertLog.triggered_at)).limit(10)
        result = await session.execute(stmt)
        alerts = result.scalars().all()
        
        print("\n--- AI PIPELINE AUDIT (v10.36) ---")
        print(f"{'ID':<8} | {'TOPIC':<10} | {'STATUS':<12} | {'IMPACT COUNT'} | {'HAS METADATA?'}")
        print("-" * 70)
        
        for a in alerts:
            status = a.metadata_json.get("backbone_discovery_status", "idle") if a.metadata_json else "idle"
            impacts = a.metadata_json.get("cascading_impacts", []) if a.metadata_json else []
            has_meta = "Yes" if a.metadata_json else "No"
            
            # Label truncation for display
            label = str(a.id)[:8]
            topic = (a.topic or "global")[:10]
            
            print(f"{label:<8} | {topic:<10} | {status:<12} | {len(impacts):<12} | {has_meta}")
            
        print("-" * 70)

if __name__ == "__main__":
    asyncio.run(audit_pipeline())
