import asyncio
import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Force Dry Run for safety
os.environ["DRY_RUN_THREADS"] = "true"
os.environ["PLATFORM_BASE_URL"] = "https://osint-web-1oev.onrender.com"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///osint_platform.db"

from sqlalchemy.future import select
from db.database import AsyncSessionLocal, Base, engine
from db.models import Report, ExternalPost, SignalRanking, Item
from article.report_job import run_report_generation
from jobs.threads_publisher_job import run_threads_publisher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_decoupling")

async def setup_test_data(session):
    # Ensure some data exists to trigger a report
    item = Item(
        id=uuid.uuid4(),
        title="Verification Test: Emerging Risk in Tech Sector",
        summary="Test summary for a high-intensity signal.",
        published_at=datetime.now(timezone.utc),
        source_url=f"https://test.com/{uuid.uuid4()}",
        source_id="test_rss",
        dedup_key=f"test_dedup_{uuid.uuid4()}",
        lightweight_score=0.9
    )
    session.add(item)
    await session.flush()
    
    ranking = SignalRanking(
        item_id=item.id,
        signal_type="Top 10 Global Risk Signals",
        score=20.0,
        rank=1
    )
    session.add(ranking)
    await session.commit()
    logger.info("Test data setup complete.")

async def verify_output_files():
    # Find the latest teaser file
    out_dir = "outputs"
    files = [f for f in os.listdir(out_dir) if f.startswith("teaser_") and f.endswith(".md")]
    if not files:
        logger.error("No teaser files found!")
        return
    
    latest_file = max([os.path.join(out_dir, f) for f in files], key=os.path.getmtime)
    logger.info(f"Checking teaser file: {latest_file}")
    with open(latest_file, "r", encoding="utf-8") as f:
        content = f.read()
        logger.info(f"Teaser Content Snippet:\n{content[:200]}...")
        
        # 1. Check for platform URL
        if "osint-web-1oev.onrender.com/?report_id=" in content:
            logger.info("✅ PLATFORM_BASE_URL logic verified in teaser.")
        else:
            logger.error("❌ PLATFORM_BASE_URL logic missing in teaser!")
            
        # 2. Check for lack of 'Substack' branding (CTA)
        if "Substack" in content:
             logger.warning("⚠️ 'Substack' string still found in teaser - check template.")
        else:
             logger.info("✅ Substack branding removed from teaser CTA.")

async def test_fault_tolerance():
    logger.info("--- Testing Substack Fault Tolerance ---")
    async with AsyncSessionLocal() as session:
        # Mock Substack failure
        with patch("article.report_job.create_draft", side_effect=Exception("Substack API Timeout")):
            teaser, status, msg = await run_report_generation(
                session, 
                report_type="test_v", 
                period_days=1, 
                topic=None, 
                auto_post_threads=True
            )
            logger.info(f"Report generation finished with status: {status}")
            
            post = (await session.execute(select(ExternalPost).where(ExternalPost.status == "pending"))).scalars().first()
            if post:
                logger.info(f"✅ Threads post queued despite Substack failure. Post ID: {post.id}")
            else:
                logger.error("❌ Threads post NOT queued on Substack failure!")

async def test_publisher_bypass():
    logger.info("--- Testing Publisher Substack Bypass ---")
    async with AsyncSessionLocal() as session:
        # Check if we can find the pending post
        await run_threads_publisher(session)
        logger.info("✅ run_threads_publisher finished. Check logs for 'Target Platform URL' and bypass evidence.")

async def main():
    async with AsyncSessionLocal() as session:
        await setup_test_data(session)
    
    await test_fault_tolerance()
    await verify_output_files()
    await test_publisher_bypass()

if __name__ == "__main__":
    asyncio.run(main())
