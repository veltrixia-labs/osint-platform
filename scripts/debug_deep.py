import sys, asyncio, uuid, json
sys.path.insert(0, '.')
from db.database import AsyncSessionLocal
from db.models import AlertLog, Stakeholder
from processor.impact_discovery import ImpactDiscoveryEngine
from sqlalchemy.future import select

async def simulate_specific():
    async with AsyncSessionLocal() as db:
        # Get the latest alert
        stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(1)
        alert = (await db.execute(stmt)).scalar_one_or_none()
        if not alert:
            print("No alerts found in DB")
            return
            
        print(f"Simulating analysis for Alert ID: {alert.id}")
        print(f"Title: {alert.target_label}")
        print(f"Metadata Type: {type(alert.metadata_json)}")
        
        engine = ImpactDiscoveryEngine(db)
        try:
            # Replicate the logic in alerts.py
            print("Running Discovery...")
            discovery_results = await engine.run_discovery(
                trigger_item_id=uuid.uuid4(),
                title=alert.target_label,
                summary=(alert.metadata_json.get("description") if alert.metadata_json else None) or f"Triggered on {alert.topic}"
            )
            print(f"Discovery complete. Found {len(discovery_results)} results.")
            
            if discovery_results:
                # Replicate the dict() crash point
                print("Attempting to update metadata...")
                updated_meta = dict(alert.metadata_json) if alert.metadata_json else {}
                updated_meta["cascading_impacts"] = discovery_results
                alert.metadata_json = updated_meta
                print("Metadata update successful.")
                await db.commit()
                print("Commit successful.")
            else:
                print("No results returned.")
                
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(simulate_specific())
