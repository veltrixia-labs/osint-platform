import asyncio
from db.database import AsyncSessionLocal
from db.models import AlertLog
from sqlalchemy import select
import json

async def check():
    async with AsyncSessionLocal() as db:
        stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(5)
        rows = (await db.execute(stmt)).scalars().all()
        for r in rows:
            meta = r.metadata_json or {}
            fa = meta.get('free_alert', {})
            news = fa.get('related_news', [])
            print(f"Alert ID: {r.id}")
            print(f"Has free_alert: {bool(fa)}")
            print(f"Related news count in meta: {len(news)}")
            if news:
                print(f"First news title: {news[0].get('title')}")
                print(f"First news URL: {news[0].get('url')}")
            print("-" * 20)

if __name__ == '__main__':
    asyncio.run(check())
