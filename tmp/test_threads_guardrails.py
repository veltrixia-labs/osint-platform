import asyncio
import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

# No DB needed for mock tests
from jobs.threads_publisher_job import check_threads_guardrails

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_guardrails")

async def test_quiet_hours():
    logger.info("--- Testing Quiet Hours (02:00 UTC) ---")
    mock_now = datetime(2026, 3, 20, 2, 0, 0, tzinfo=timezone.utc)
    mock_session = AsyncMock()
    
    with patch("jobs.threads_publisher_job.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        ok, reason = await check_threads_guardrails(mock_session)
        if not ok and "Quiet hours" in reason:
            logger.info(f"✅ Correctly blocked: {reason}")
        else:
            logger.error(f"❌ Failed to block or wrong reason: {reason}")

async def test_cooldown():
    logger.info("--- Testing Cooldown (30 mins ago) ---")
    now = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    last_post_time = now - timedelta(minutes=30)
    
    # Mock DB response for last post
    mock_last_post = MagicMock()
    mock_last_post.published_at = last_post_time
    
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_last_post
    
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_execute_result
    
    with patch("jobs.threads_publisher_job.datetime") as mock_dt:
        mock_dt.now.return_value = now
        ok, reason = await check_threads_guardrails(mock_session)
        if not ok and "Cooldown active" in reason:
            logger.info(f"✅ Correctly blocked: {reason}")
        else:
            logger.error(f"❌ Failed to block or wrong reason: {reason}")

async def test_daily_cap():
    logger.info("--- Testing Daily Cap (5 posts today) ---")
    now = datetime(2026, 3, 20, 15, 0, 0, tzinfo=timezone.utc)
    
    # 1. First call for cooldown (let's say it passes)
    mock_last_post = MagicMock()
    mock_last_post.published_at = now - timedelta(hours=2)
    
    # 2. Second call for count
    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 5 # Cap reached
    
    mock_session = AsyncMock()
    # Side effect for the two executes in check_threads_guardrails
    mock_session.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: mock_last_post),
        MagicMock(scalar_one=lambda: 5)
    ]
    
    with patch("jobs.threads_publisher_job.datetime") as mock_dt:
        mock_dt.now.return_value = now
        ok, reason = await check_threads_guardrails(mock_session)
        if not ok and "Daily cap reached" in reason:
            logger.info(f"✅ Correctly blocked: {reason}")
        else:
            logger.error(f"❌ Failed to block or wrong reason: {reason}")

async def test_pass_all():
    logger.info("--- Testing Pass All (12:00 UTC, clean slate) ---")
    now = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    
    mock_last_post = MagicMock()
    mock_last_post.published_at = now - timedelta(hours=2)
    
    mock_session = AsyncMock()
    mock_session.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: mock_last_post),
        MagicMock(scalar_one=lambda: 1) # Only 1 post today
    ]
    
    with patch("jobs.threads_publisher_job.datetime") as mock_dt:
        mock_dt.now.return_value = now
        ok, reason = await check_threads_guardrails(mock_session)
        if ok:
            logger.info("✅ Correctly allowed.")
        else:
            logger.error(f"❌ Wrongly blocked: {reason}")

async def main():
    await test_quiet_hours()
    await test_cooldown()
    await test_daily_cap()
    await test_pass_all()

if __name__ == "__main__":
    asyncio.run(main())
