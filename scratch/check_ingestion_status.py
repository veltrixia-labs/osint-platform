import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import RawItem, Item, AlertLog
from sqlalchemy import select, func, desc

async def check_ingestion_status():
    async with AsyncSessionLocal() as db:
        print("=" * 80)
        print(f"INGESTION PIPELINE STATUS CHECK - {datetime.now(timezone.utc).isoformat()}")
        print("=" * 80)

        for name, model, time_col in [
            ("RawItem", RawItem, RawItem.created_at),
            ("Item", Item, Item.created_at),
            ("AlertLog", AlertLog, AlertLog.triggered_at)
        ]:
            print(f"\n[{name}] Statistics:")
            for days in [1, 7, 14, 30]:
                lookback = datetime.now(timezone.utc) - timedelta(days=days)
                stmt = select(func.count(model.id)).where(time_col >= lookback)
                count = (await db.execute(stmt)).scalar()
                print(f"  Last {days:2} Days: {count:5}")
            
            # Latest entry
            stmt_latest = select(model).order_by(desc(time_col)).limit(1)
            latest = (await db.execute(stmt_latest)).scalar_one_or_none()
            if latest:
                if name == "RawItem":
                    print(f"  Latest Created: {latest.created_at}")
                    print(f"  Latest Source:  {latest.source_system}")
                    print(f"  Latest Title:   {latest.payload_json.get('title', 'N/A')}")
                elif name == "Item":
                    print(f"  Latest Created: {latest.created_at}")
                    print(f"  Latest Source:  {latest.source_name}")
                    print(f"  Latest Title:   {latest.title}")
                elif name == "AlertLog":
                    print(f"  Latest Triggered: {latest.triggered_at}")
                    print(f"  Latest Topic:     {latest.topic}")
                    print(f"  Latest Target:    {latest.target_label}")
            else:
                print("  No entries found.")

if __name__ == "__main__":
    asyncio.run(check_ingestion_status())
