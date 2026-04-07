import asyncio
import logging
import sys
import os

# プロジェクトルートをパスに追加
sys.path.append(os.getcwd())

from db.database import AsyncSessionLocal
from jobs.main_scheduler import pipeline_full_processing, daily_reports_wrapper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("ForceRunner")

async def force_sync():
    logger.info("============== FORCE SYNC START ==============")
    async with AsyncSessionLocal() as session:
        # 1. パイプライン全体（収集〜アラート生成）を強制実行
        logger.info("Step 1: Running full pipeline (Ingest -> Classify -> Signal -> Alert)...")
        await pipeline_full_processing()
        
        # 2. デイリーレポートを強制生成
        logger.info("Step 2: Generating Daily Reports...")
        await daily_reports_wrapper()
        
    logger.info("============== FORCE SYNC COMPLETED ==============")

if __name__ == "__main__":
    asyncio.run(force_sync())
