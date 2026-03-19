import asyncio
import os
import sys

# Add project root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import uuid
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone, timedelta
from article.report_job import handle_threads_autopost
from db.models import ExternalPost

class TestThreadsStability(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = AsyncMock()
        self.report_id = uuid.uuid4()
        self.teaser = "Test Teaser with Substack link: https://substack.com/test"
        
    @patch("article.report_job.datetime")
    async def test_quiet_hours(self, mock_dt):
        # Set time to 02:00 UTC (within quiet hours 01:00-05:00)
        mock_dt.now.return_value = datetime(2026, 3, 17, 2, 0, 0, tzinfo=timezone.utc)
        
        with patch("article.report_job.logger") as mock_logger:
            await handle_threads_autopost(self.db, self.report_id, self.teaser, "global")
            mock_logger.info.assert_any_call("Threads quiet hours active (2:00 UTC). Skipping auto-post.")

    @patch("article.report_job.datetime")
    async def test_cooldown_enforcement(self, mock_dt):
        # Set time to 12:00 UTC
        now = datetime(2026, 3, 17, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now
        
        # Mock recent post (30 mins ago)
        recent_post = ExternalPost(platform="threads", status="success", published_at=now - timedelta(minutes=30))
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [recent_post]
        self.db.execute.return_value = mock_result
        
        with patch("article.report_job.logger") as mock_logger:
            # We also need to mock the deduplication check so it doesn't return existing post
            mock_stmt_res = MagicMock()
            mock_stmt_res.scalars.return_value.first.return_value = None
            self.db.execute.side_effect = [mock_result, mock_stmt_res]
            
            await handle_threads_autopost(self.db, self.report_id, self.teaser, "global")
            mock_logger.info.assert_any_call("Threads cooldown active (last post < 1h ago). Skipping.")

    @patch("article.report_job.datetime")
    async def test_daily_cap(self, mock_dt):
        now = datetime(2026, 3, 17, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now
        
        # Mock 5 posts in last 24h
        posts = [ExternalPost(platform="threads", status="success", published_at=now - timedelta(hours=i)) for i in range(5)]
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = posts
        self.db.execute.return_value = mock_result
        
        with patch("article.report_job.logger") as mock_logger:
            await handle_threads_autopost(self.db, self.report_id, self.teaser, "global")
            mock_logger.warning.assert_any_call("Threads daily cap reached (5 posts). Skipping.")

if __name__ == "__main__":
    unittest.main()
