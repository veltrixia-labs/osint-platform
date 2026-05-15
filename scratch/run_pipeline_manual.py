import asyncio
import sys
import os
import logging
from datetime import datetime, timezone
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.main_scheduler import pipeline_full_processing

# Set logging to INFO to see the progress
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_manual_pipeline():
    print("=" * 80)
    print("MANUAL FULL PIPELINE TEST")
    print("=" * 80)
    
    try:
        print("[1] Starting pipeline_full_processing...")
        await pipeline_full_processing()
        print("[2] pipeline_full_processing finished.")
    except Exception as e:
        print(f"[ERROR] pipeline_full_processing failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_manual_pipeline())
