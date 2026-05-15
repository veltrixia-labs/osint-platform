import asyncio
from sqlalchemy import select
from db.database import AsyncSessionLocal
from db.models import RawItem

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RawItem).order_by(RawItem.fetched_at.desc()).limit(10)
        )
        items = result.scalars().all()

        print(f"RawItem count shown: {len(items)}")
        for item in items:
            payload = item.payload_json or {}
            print("-" * 80)
            print("source_id:", item.source_id)
            print("source_group:", item.source_group)
            print("title:", payload.get("title"))
            print("link:", payload.get("link"))
            print("published:", payload.get("published"))

asyncio.run(main())