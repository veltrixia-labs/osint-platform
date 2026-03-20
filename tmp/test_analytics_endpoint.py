import asyncio
import os
import uuid
import logging
from datetime import datetime, timezone

# Use local test DB
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///osint_platform.db"

from db.database import AsyncSessionLocal, engine
from db.models import AnalyticsEvent, Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_analytics")

async def test_analytics_logic():
    # Create table if not exists
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # 1. Test unauthenticated logging (simulated)
        report_id = uuid.uuid4()
        
        event = AnalyticsEvent(
            event_type="preview_view",
            report_id=report_id,
            metadata_json={"utm_source": "threads", "visitor_id": "test-vid"}
        )
        session.add(event)
        await session.commit()
        logger.info(f"✅ Logged unauthenticated event: {event.id}")

        # 2. Test authenticated logging
        user_id = uuid.uuid4() # Mock user ID
        event_auth = AnalyticsEvent(
            event_type="full_view",
            report_id=report_id,
            user_id=user_id,
            metadata_json={"utm_source": "threads", "visitor_id": "test-vid"}
        )
        session.add(event_auth)
        await session.commit()
        logger.info(f"✅ Logged authenticated event: {event_auth.id}")

        # 3. Verify total count
        from sqlalchemy import func, select
        count_stmt = select(func.count(AnalyticsEvent.id))
        count = (await session.execute(count_stmt)).scalar()
        logger.info(f"Total analytics events in DB: {count}")

async def main():
    await test_analytics_logic()

if __name__ == "__main__":
    asyncio.run(main())
