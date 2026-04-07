import asyncio
from sqlalchemy import select, func
from db.database import AsyncSessionLocal
from db.models import Item, TrendSignal, AlertLog, Report

async def check_db():
    async with AsyncSessionLocal() as session:
        items = await session.execute(select(func.count(Item.id)))
        signals = await session.execute(select(func.count(TrendSignal.id)))
        alerts = await session.execute(select(func.count(AlertLog.id)))
        reports = await session.execute(select(func.count(Report.id)))
        
        print(f"Items: {items.scalar()}")
        print(f"Signals: {signals.scalar()}")
        print(f"Alerts: {alerts.scalar()}")
        print(f"Reports: {reports.scalar()}")

if __name__ == "__main__":
    asyncio.run(check_db())
