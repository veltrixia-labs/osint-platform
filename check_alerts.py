import asyncio
import sys
from sqlalchemy import select
from db.database import AsyncSessionLocal
from db.models import AlertLog

async def main():
    async with AsyncSessionLocal() as session:
        stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(5)
        res = await session.execute(stmt)
        alerts = res.scalars().all()
        for a in alerts:
            meta = a.metadata_json or {}
            print(f"ID: {a.id}")
            print(f"Label: {a.target_label}")
            print(f"Time: {a.triggered_at}")
            print(f"Status: {meta.get('backbone_discovery_status')}")
            print(f"TS: {meta.get('backbone_discovery_ts')}")
            print("-------------------------")

if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
