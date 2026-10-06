import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import AsyncSessionLocal, run_migrations
from jobs.main_scheduler import pipeline_full_processing, daily_reports_wrapper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("dev_sync_engine")

async def run_sync():
    logger.info("Starting MANUAL ENGINE SYNC...")
    
    # 0. Database Schema Setup
    logger.info("[SYNC] Phase 0: Initializing Database Schema (Alembic)...")
    try:
        run_migrations()
    except Exception as e:
        logger.error(f"Migration failed: {e}. Continue anyway if schema exists.")

    logger.info("Initializing DB Session...")
    
    try:
        # 1. Full Pipeline Sync (Ingest -> Normalize -> Classify -> Signal -> Alert)
        logger.info("[SYNC] Phase 1: Pipeline Full Processing (Alerts & Signals)")
        await pipeline_full_processing()
        
        # 2. Report Generation Sync
        # Weekly reports were retired 2026-10-06; daily generation is itself a no-op
        # (report_orchestrator.py), kept here only as the scheduler still registers it.
        logger.info("[SYNC] Phase 2: Daily report wrapper")
        await daily_reports_wrapper()
        
        logger.info("SUCCESS: Manual Sync Completed. Dashboard should now reflect fresh intelligence.")
        
    except Exception as e:
        logger.error(f"SYNC FAILED: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_sync())
