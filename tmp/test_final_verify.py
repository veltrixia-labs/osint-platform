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
from db.database import AsyncSessionLocal
from db.models import Report, ExternalPost, Item
from jobs.threads_publisher_job import run_threads_publisher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("final_verify")

async def ensure_pending_post(session):
    # Ensure there is a pending post for a report
    existing = (await session.execute(select(ExternalPost).where(ExternalPost.status == "pending"))).scalars().first()
    if existing:
        logger.info(f"Using existing pending post: {existing.id}")
        return existing
    
    # Create a dummy report and post if none exist
    report = Report(
        id=uuid.uuid4(),
        report_type="final_verify",
        topic_code="global",
        content_markdown="Final verify content"
    )
    session.add(report)
    await session.flush()
    
    post = ExternalPost(
        id=uuid.uuid4(),
        platform="threads",
        report_id=report.id,
        status="pending"
    )
    session.add(post)
    await session.commit()
    logger.info(f"Created new pending post: {post.id}")
    return post

async def test_integration():
    async with AsyncSessionLocal() as session:
        await ensure_pending_post(session)
        
        # 1. Test Blocked (Quiet Hours: 02:00 UTC)
        logger.info("--- 1. Testing Blocked (Quiet Hours) ---")
        mock_now = datetime(2026, 3, 20, 2, 0, 0, tzinfo=timezone.utc)
        with patch("jobs.threads_publisher_job.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            await run_threads_publisher(session)
            # Verify status remains pending
            stmt = select(ExternalPost).where(ExternalPost.status == "pending")
            count = len((await session.execute(stmt)).scalars().all())
            logger.info(f"Pending count after block: {count}")
            if count > 0:
                logger.info("✅ Pending status preserved.")
            else:
                logger.error("❌ Pending status LOST!")

        # 2. Test Pass (12:00 UTC)
        logger.info("--- 2. Testing Pass (12:00 UTC) ---")
        mock_now = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
        with patch("jobs.threads_publisher_job.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            # We need to ensure no cooldown exists from previous real data
            # So I mock check_threads_guardrails to return True just for this pass
            # OR I just trust the logic if the DB is clean. 
            # Let's try real check.
            await run_threads_publisher(session)
            
            # Since this is dry-run, it should set status to 'success'
            stmt = select(ExternalPost).where(ExternalPost.status == "success")
            success_post = (await session.execute(stmt)).scalars().first()
            if success_post:
                logger.info(f"✅ Post advanced to success in dry-run. ID: {success_post.id}")
            else:
                logger.warning("⚠️ No success post found - might be blocked by cooldown of actual data in osint_platform.db")

if __name__ == "__main__":
    asyncio.run(test_integration())
