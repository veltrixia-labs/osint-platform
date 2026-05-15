import asyncio
from sqlalchemy import select, func
from db.database import AsyncSessionLocal
from db.models import TrendSignal

async def main():
    async with AsyncSessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(TrendSignal))
        print("TrendSignal total:", count)

        result = await session.execute(
            select(TrendSignal)
            .order_by(TrendSignal.created_at.desc())
            .limit(10)
        )

        for sig in result.scalars().all():
            print("-" * 80)
            print("id:", sig.id)
            print("created_at:", sig.created_at)
            print("topic:", sig.topic)
            print("trend_type:", sig.trend_type)
            print("target_label:", sig.target_label)
            print("intensity_score:", sig.intensity_score)
            print("metrics_json:", sig.metrics_json)

asyncio.run(main())