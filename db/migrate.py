"""
Migration script for OSINT DB:
- Adds source_id, source_group, reliability_weight columns to raw_items and items tables.
- Creates source_registry and source_health_logs tables if not exist.
"""
import asyncio
import logging
from db.database import engine, Base
from db.models import (
    RawItem, Item, SourceRegistry, SourceHealthLog,
    Topic, ItemTopic, Report, SignalRanking, ArticleOutput, PdfJob, JobRun,
    EventCluster, ExternalPost, TrendSignal
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NEW_COLUMNS = [
    ("raw_items", "source_id", "TEXT"),
    ("raw_items", "source_group", "TEXT"),
    ("raw_items", "reliability_weight", "REAL"),
    ("items", "source_id", "TEXT"),
    ("items", "source_group", "TEXT"),
    ("items", "reliability_weight", "REAL"),
]

async def run_migration():
    async with engine.begin() as conn:
        # 1. Create all new tables (source_registry, source_health_logs) if not exist
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Ensured all tables exist.")

        # 2. Add missing columns to existing tables using raw SQL
        import aiosqlite
        db_path = engine.url.database  # e.g. "osint.db"
        async with aiosqlite.connect(db_path) as db:
            for table, column, col_type in NEW_COLUMNS:
                try:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    await db.commit()
                    logger.info(f"Added column '{column}' to '{table}'")
                except Exception as e:
                    if "duplicate column name" in str(e).lower():
                        logger.info(f"Column '{column}' already exists in '{table}', skipping.")
                    else:
                        logger.warning(f"Could not add '{column}' to '{table}': {e}")

    logger.info("Migration complete.")

if __name__ == "__main__":
    asyncio.run(run_migration())
