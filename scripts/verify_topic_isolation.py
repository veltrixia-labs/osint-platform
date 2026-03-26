import asyncio
import logging
import sys
import os
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.signal_job import run_signal
from article.report_job import run_all_reports

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def verify_isolation():
    logger.info("Starting Topic Isolation Verification...")
    
    async with AsyncSessionLocal() as session:
        # 1. Run Signal Job to populate rankings with new topic-scoped logic
        logger.info("--- Step 1: Running Topic-Scoped Signal Job ---")
        await run_signal(session)
        
        # 2. Run Report Generation for specific topics
        logger.info("--- Step 2: Generating Reports ---")
        # We run for AI, Crypto, and Energy as requested
        # We use a 1-day period
        topics_to_test = ["ai_semiconductor_intelligence", "crypto_geopolitics", "energy_resource_risk"]
        
        from article.report_job import run_report_generation
        
        for topic in topics_to_test:
            logger.info(f"\n>>> TESTING TOPIC: {topic}")
            teaser, status, reason = await run_report_generation(
                session, 
                report_type="daily_global", 
                period_days=1, 
                topic=topic,
                auto_post_threads=False
            )
            logger.info(f"Result for {topic}: Status={status}, Reason={reason}")
            
    logger.info("\nVerification Complete. Please check the 'outputs/' directory and logs above for isolation confirmation.")

if __name__ == "__main__":
    asyncio.run(verify_isolation())
