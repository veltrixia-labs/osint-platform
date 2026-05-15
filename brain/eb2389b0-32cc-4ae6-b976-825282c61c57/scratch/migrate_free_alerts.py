import asyncio
import logging
from db.database import AsyncSessionLocal
from db.models import AlertLog
from sqlalchemy import select
from jobs.free_alert_feed_generator import persist_free_alert_feed_item

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

async def migrate():
    async with AsyncSessionLocal() as db:
        # Find all AlertLogs
        stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc())
        rows = (await db.execute(stmt)).scalars().all()
        
        logger.info(f"Starting migration for {len(rows)} alerts...")
        
        for r in rows:
            try:
                # This will re-run the matching logic and update metadata_json["free_alert"]
                # with the new structured related_news field.
                await persist_free_alert_feed_item(db, r)
                logger.info(f"Successfully updated Alert ID: {r.id}")
            except Exception as e:
                logger.error(f"Failed to update Alert ID {r.id}: {e}")
        
        await db.commit()
        logger.info("Migration complete.")

if __name__ == '__main__':
    asyncio.run(migrate())
