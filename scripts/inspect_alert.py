import asyncio
import json
from sqlalchemy import select, desc
from db.database import AsyncSessionLocal
from db.models import AlertLog

async def inspect_alert():
    async with AsyncSessionLocal() as session:
        # Get the most recent alert
        stmt = select(AlertLog).order_by(desc(AlertLog.triggered_at)).limit(1)
        result = await session.execute(stmt)
        alert = result.scalar_one_or_none()
        
        if not alert:
            print("No alerts found.")
            return

        print(f"\n--- INSPECTING ALERT: {alert.id} ---")
        print(f"Target: {alert.target_label}")
        print(f"Topic: {alert.topic}")
        
        status = alert.metadata_json.get("backbone_discovery_status") if alert.metadata_json else "None (No Metadata)"
        print(f"Status (from info): {status}")
        
        print("\nMETADATA_JSON Keys:", list(alert.metadata_json.keys()) if alert.metadata_json else "None")
        
        print("\n--- END INSPECTION ---")

if __name__ == "__main__":
    asyncio.run(inspect_alert())
