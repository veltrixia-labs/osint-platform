import asyncio
import sys
import uuid
from sqlalchemy import select
from db.database import AsyncSessionLocal
from db.models import AlertLog
from processor.impact_discovery import ImpactDiscoveryEngine

async def trigger_reanalysis(alert_id_str: str):
    aid = uuid.UUID(alert_id_str)
    async with AsyncSessionLocal() as session:
        # Fetch alert to get title/summary
        stmt = select(AlertLog).where(AlertLog.id == aid)
        alert = (await session.execute(stmt)).scalar_one_or_none()
        
        if not alert:
            print(f"Alert {alert_id_str} not found.")
            return

        print(f"Triggering re-analysis for: {alert.target_label}")
        print(f"Current Status: {alert.metadata_json.get('backbone_discovery_status', 'None')}")
        
        title = alert.target_label
        summary = (alert.metadata_json.get("description") or title)
        
        engine = ImpactDiscoveryEngine(session)
        # Note: run_discovery internalizes the status update to AlertLog if alert_id is passed
        results = await engine.run_discovery(
            trigger_item_id=uuid.uuid4(),
            title=title,
            summary=summary,
            alert_id=aid
        )
        
        print(f"\nAnalysis complete. Results found: {len(results)}")
        
        # Re-fetch to check committed status
        await session.refresh(alert)
        print(f"Final Status in DB: {alert.metadata_json.get('backbone_discovery_status')}")
        
        if results:
            print("\nSAMPLE FINDING:")
            print(json.dumps(results[0], indent=2))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py scripts/reanalyze_alert.py <alert_id>")
        sys.exit(1)
        
    import json
    asyncio.run(trigger_reanalysis(sys.argv[1]))
