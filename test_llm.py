import asyncio
import uuid
import sys
import logging
from db.database import AsyncSessionLocal
from processor.impact_discovery import ImpactDiscoveryEngine
from db.models import AlertLog
from sqlalchemy.future import select

logging.basicConfig(level=logging.DEBUG)

async def main():
    async with AsyncSessionLocal() as session:
        # Find the alert 'Vance's Trip to Islamabad...'
        stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(1)
        res = await session.execute(stmt)
        alert = res.scalar_one_or_none()
        
        if not alert:
            print("No alert found.")
            return

        print(f"Testing LLM for Alert: {alert.id} | {alert.target_label}")
        engine = ImpactDiscoveryEngine(session)
        
        try:
            summary = "Test summary"
            if alert.metadata_json and "description" in alert.metadata_json:
                summary = alert.metadata_json["description"]
            
            result = await engine.run_discovery(uuid.uuid4(), alert.target_label, summary, alert.id)
            print("=== RESULT ===")
            print(result)
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
