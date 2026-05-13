import asyncio
import logging
import os
import httpx
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.database import AsyncSessionLocal
from db.models import ExternalPost, Report
from sqlalchemy import func
from integrations.threads_client import create_threads_posting_client, threads_mock_force_enabled

logger = logging.getLogger(__name__)

async def check_threads_guardrails(db: AsyncSession) -> tuple[bool, str]:
    """
    Checks for Quiet Hours, Cooldown, and Daily Cap.
    Returns (True, "ok") if allowed, (False, reason) otherwise.
    """
    now = datetime.now(timezone.utc)
    
    # 1. Quiet Hours (UTC 01:00 - 05:00)
    if 1 <= now.hour < 5:
        return False, f"Quiet hours (UTC {now.hour:02d}:00)"

    # 2. Cooldown (60 minutes)
    # Status used in code is 'success'
    stmt_last = select(ExternalPost).where(
        ExternalPost.platform == "threads",
        ExternalPost.status == "success"
    ).order_by(ExternalPost.published_at.desc()).limit(1)
    
    last_post = (await db.execute(stmt_last)).scalar_one_or_none()
    if last_post and last_post.published_at:
        elapsed = now - last_post.published_at
        if elapsed < timedelta(minutes=60):
            wait_min = 60 - int(elapsed.total_seconds() / 60)
            return False, f"Cooldown active ({wait_min}m remaining)"

    # 3. Daily Cap (5 per day UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt_today = select(func.count(ExternalPost.id)).where(
        ExternalPost.platform == "threads",
        ExternalPost.status == "success",
        ExternalPost.published_at >= today_start
    )
    
    today_count = (await db.execute(stmt_today)).scalar_one() or 0
    if today_count >= 5:
        return False, f"Daily cap reached ({today_count}/5 posted today UTC)"

    return True, "ok"

async def run_threads_publisher(db: AsyncSession):
    """
    Polls for 'pending' Threads posts and executes them if guardrails pass.
    """
    # Check Guardrails First
    is_allowed, reason = await check_threads_guardrails(db)
    if not is_allowed:
        logger.info(f"Threads publisher skipped: {reason}")
        return

    logger.info("Starting Threads Platform Polling Job...")
    
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
    mock_force = threads_mock_force_enabled()
    
    async with httpx.AsyncClient() as client:
        for post in pending_posts:
            # 1. Retrieve associated Report
            report = (await db.execute(select(Report).where(Report.id == post.report_id))).scalar_one_or_none()
            # 2. Skip Substack live-check (Phase 34 Decoupling)
            # The internal platform is live as soon as the report exists.
            target_url = f"{os.getenv('DOMAIN_URL', 'https://veltrixia.net')}/?report_id={report.id}"
            logger.info(f"Target Platform URL: {target_url}")
                
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
            logger.info(f"Report is LIVE! Attempting Threads post for Report {report.id}...")
            
            if dry_run and not mock_force:
                logger.info(f"[DRY RUN] Would post to Threads: {normalized_text[:50]}...")
                post.status = "success"  # advance queue without network
            else:
                try:
                    t_client = create_threads_posting_client(
                        access_token or "",
                        user_id or "",
                        app_id,
                        app_secret,
                    )
                    if app_secret and not mock_force:
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
