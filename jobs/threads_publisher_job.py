import asyncio
import logging
import os
import httpx
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.database import AsyncSessionLocal
from db.models import ExternalPost, Report
from integrations.threads_client import ThreadsClient
from integrations.substack_client import get_final_url

logger = logging.getLogger(__name__)

async def run_threads_publisher(db: AsyncSession):
    """
    Polls for 'pending' Threads posts, verifies that the target Substack 
    article is actually live (HTTP 200), and then posts to Threads.
    """
    logger.info("Starting Threads Substack-Confirmation Polling Job...")
    
    stmt = select(ExternalPost).where(
        ExternalPost.platform == "threads",
        ExternalPost.status == "pending"
    )
    pending_posts = (await db.execute(stmt)).scalars().all()
    
    if not pending_posts:
        logger.info("No pending Threads posts found.")
        return
        
    access_token = os.getenv("THREADS_ACCESS_TOKEN")
    user_id = os.getenv("THREADS_USER_ID")
    app_id = os.getenv("THREADS_APP_ID")
    app_secret = os.getenv("THREADS_APP_SECRET")
    dry_run = os.getenv("DRY_RUN_THREADS", "true").lower() == "true"
    
    async with httpx.AsyncClient() as client:
        for post in pending_posts:
            # 1. Retrieve associated Report
            report = (await db.execute(select(Report).where(Report.id == post.report_id))).scalar_one_or_none()
            if not report or not report.substack_slug:
                logger.error(f"Cannot publish Threads post {post.id} - Invalid or missing Report metadata.")
                post.status = "failure"
                post.error_message = "Missing report metadata"
                continue
                
            # 2. Check if Substack article is live (HTTP 200)
            target_url = get_final_url(report.substack_slug)
            try:
                response = await client.head(target_url, timeout=5.0)
                if response.status_code == 405 or response.status_code == 403:
                    # Substack might block HEAD. Fallback to GET.
                    response = await client.get(target_url, timeout=5.0)
                
                if response.status_code != 200:
                    logger.info(f"Substack article not live yet (Status {response.status_code}) for '{report.substack_slug}'. Keeping pending.")
                    continue
            except Exception as e:
                logger.warning(f"Failed to ping Substack url '{target_url}': {e}. Keeping pending.")
                continue
                
            # 3. If live, reconstruct the teaser file path
            topic_str = report.topic_code if report.topic_code else "global"
            date_str = report.created_at.strftime('%Y%m%d') if report.created_at else datetime.now(timezone.utc).strftime('%Y%m%d')
            base_name = f"{topic_str}_{report.report_type}_{date_str}_en"
            
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            teaser_file = os.path.join(base_dir, "outputs", f"teaser_{base_name}.md")
            
            if not os.path.exists(teaser_file):
                logger.error(f"Teaser file missing for Threads post {post.id} ({teaser_file}). Marking failure.")
                post.status = "failure"
                post.error_message = f"Missing teaser file: {teaser_file}"
                continue
                
            with open(teaser_file, "r", encoding="utf-8") as f:
                teaser_text = f.read()
                
            # 4. Cleanup Teaser text
            normalized_text = teaser_text.replace("\n\n\n", "\n\n").strip()
            
            if len(normalized_text) < 10 or len(normalized_text) > 500:
                logger.error(f"Threads text validation failed for post {post.id}: Length {len(normalized_text)}")
                post.status = "failure"
                post.error_message = "Invalid text length"
                continue
                
            # 5. Execute Thread Post
            logger.info(f"Substack article is LIVE! Attempting Threads post for Report {report.id}...")
            
            if dry_run:
                logger.info(f"[DRY RUN] Would post to Threads: {normalized_text[:50]}...")
                post.status = "success" # Just for mock advancement
            else:
                try:
                    t_client = ThreadsClient(access_token, user_id, app_id, app_secret)
                    if app_secret:
                        await t_client.refresh_access_token()
                    
                    result = await t_client.post_thread(normalized_text)
                    if result["success"]:
                        post.status = "success"
                        post.external_id = result.get("media_id")
                        post.container_id = result.get("container_id")
                        post.published_at = datetime.fromisoformat(result["published_at"]) if result["published_at"] else datetime.now(timezone.utc)
                    else:
                        post.status = "failure"
                        post.error_message = result.get("error")
                except Exception as e:
                    logger.error(f"Threads API crash for post {post.id}: {e}")
                    post.status = "failure"
                    post.error_message = str(e)
                    
            db.add(post)
            await db.commit()

if __name__ == "__main__":
    async def main():
        async with AsyncSessionLocal() as db:
            await run_threads_publisher(db)
    asyncio.run(main())
