import asyncio
from sqlalchemy import select
from db.database import AsyncSessionLocal
from db.models import AlertLog

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(20)
        )
        alerts = result.scalars().all()

        for a in alerts:
            meta = a.metadata_json or {}
            evidence = meta.get("evidence_list") or []
            print("-" * 80)
            print("title:", a.target_label)
            print("topic:", a.topic)
            print("severity:", a.severity)
            print("triggered_at:", a.triggered_at)
            print("evidence_count:", len(evidence))
            print("domains:", [e.get("domain") for e in evidence])

asyncio.run(main())