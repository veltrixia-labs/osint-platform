import asyncio, json
from db.database import AsyncSessionLocal
from db.models import AlertLog
from sqlalchemy.future import select
from sqlalchemy import cast, String

async def test():
    async with AsyncSessionLocal() as db:
        stmt = (
            select(AlertLog)
            .where(cast(AlertLog.metadata_json, String).contains("free_alert"))
            .order_by(AlertLog.triggered_at.desc())
            .limit(3)
        )
        rows = (await db.execute(stmt)).scalars().all()
        print(f"Found {len(rows)} AlertLogs with free_alert")
        for r in rows:
            fa = r.metadata_json.get("free_alert", {})
            summary = {k: v for k, v in fa.items() if k != "content_markdown"}
            print(json.dumps(summary, indent=2))

asyncio.run(test())
