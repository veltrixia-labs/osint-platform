import asyncio
import logging
from db.database import AsyncSessionLocal
from analysis.trend_engine import detect_trends

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_trend_analysis(db: AsyncSessionLocal = None):
    """Orchestrates trend analysis and persists results."""
    logger.info("--- Starting Trend Analysis Job ---")
    if db is None:
        async with AsyncSessionLocal() as session:
            await _execute(session)
    else:
        await _execute(db)
    logger.info("--- Trend Analysis Job Finished ---")

async def _execute(db):
    try:
        await detect_trends(db)
        await db.commit()
        logger.info("Trend analysis results committed.")
    except Exception as e:
        logger.error(f"Trend analysis job failed: {e}")
        await db.rollback()

if __name__ == "__main__":
    asyncio.run(run_trend_analysis())
