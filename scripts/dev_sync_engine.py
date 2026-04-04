import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import AsyncSessionLocal
from jobs.main_scheduler import pipeline_full_processing, daily_reports_wrapper, weekly_reports_wrapper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("dev_sync_engine")

async def run_sync():
    logger.info("Starting MANUAL ENGINE SYNC...")
    logger.info("Initializing DB Session...")
    
    try:
        # 1. Full Pipeline Sync (Ingest -> Normalize -> Classify -> Signal -> Alert)
        logger.info("[SYNC] Phase 1: Pipeline Full Processing (Alerts & Signals)")
        await pipeline_full_processing()
        
        # 2. Report Generation Sync
        logger.info("[SYNC] Phase 2: Generating Daily & Weekly Reports (Analysis Integration)")
        await daily_reports_wrapper()
        await weekly_reports_wrapper()
        
        logger.info("SUCCESS: Manual Sync Completed. Dashboard should now reflect fresh intelligence.")
        
    except Exception as e:
        logger.error(f"SYNC FAILED: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_sync())
