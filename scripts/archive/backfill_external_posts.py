
import asyncio
import logging
import os
import sys
from uuid import UUID
from sqlalchemy import select, update

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import AsyncSessionLocal
from db.models import ExternalPost, Report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def normalize_theme(text: str) -> str:
    if not text: return ""
    return "".join(c for c in text.lower() if c.isalnum() or c.isspace()).strip()

async def backfill():
    async with AsyncSessionLocal() as db:
        logger.info("Starting Conservative ExternalPost backfill...")
        
        # 1. Fetch all posts
        stmt = select(ExternalPost)
        result = await db.execute(stmt)
        posts = result.scalars().all()
        
        updated_count = 0
        for post in posts:
            updates = {}
            
            # --- Status Recovery ---
            # Assumption: If it has an external_id, it was successful.
            if not post.status:
                if post.external_id:
                    updates['status'] = 'success'
                else:
                    updates['status'] = 'failure' # Conservative: assume failed if no platform ID
            
            # --- Category Recovery ---
            if not post.category and post.report_id:
                report_stmt = select(Report).where(Report.id == post.report_id)
                report = (await db.execute(report_stmt)).scalar()
                if report and report.topic_code:
                    updates['category'] = report.topic_code
            
            # --- Theme Normalization (Conservative) ---
            if not post.normalized_theme and post.report_id:
                # Only derive from report if we don't have the original content_preview
                # (Note: content_preview was an old column, if we renamed it we might use it)
                report_stmt = select(Report).where(Report.id == post.report_id)
                report = (await db.execute(report_stmt)).scalar()
                
                if report and report.title:
                    # Only use "Themes:" prefix as a reliable signal
                    if "Themes: " in report.title:
                        raw_theme = report.title.split("|")[0].replace("Themes: ", "").strip()
                        norm = normalize_theme(raw_theme)
                        if norm:
                            updates['normalized_theme'] = norm
                            
            if updates:
                await db.execute(
                    update(ExternalPost)
                    .where(ExternalPost.id == post.id)
                    .values(**updates)
                )
                updated_count += 1
                    
        await db.commit()
        logger.info(f"Conservative backfill complete. Updated {updated_count} rows.")

if __name__ == "__main__":
    asyncio.run(backfill())
