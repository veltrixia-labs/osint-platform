import asyncio
import sys
import os
import logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.ingest_job import run_ingest

# Set logging to DEBUG to see more details
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def run_manual_ingest():
    print("=" * 80)
    print("MANUAL INGESTION TEST")
    print("=" * 80)
    
    async with AsyncSessionLocal() as session:
        try:
            print("[1] Starting run_ingest...")
            await run_ingest(session)
            print("[2] run_ingest finished.")
        except Exception as e:
            print(f"[ERROR] run_ingest failed: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_manual_ingest())
