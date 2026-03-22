import asyncio
import os
import json
import logging
import re
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import AsyncSessionLocal
from db.models import Report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def backfill_reports(db: AsyncSession):
    """
    Parses existing reports to fix source_count and confidence_level.
    Idempotent by checking for changes before commit.
    """
    try:
        logger.info("📡 Starting production backfill for report metadata...")
        stmt = select(Report)
        result = await db.execute(stmt)
        reports = result.scalars().all()
        
        logger.info(f"Checking {len(reports)} reports...")
        
        updated_count = 0
        for r in reports:
            md = r.content_markdown or ""
            count = 0
            
            # 1. Try to parse EVIDENCE_JSON (more robust regex)
            evidence_match = re.search(r'<!--\s*EVIDENCE_JSON:\s*([\s\S]*?)\s*-->', md, re.IGNORECASE)
            if evidence_match:
                try:
                    data = json.loads(evidence_match.group(1))
                    count = len(data)
                except: pass
            
            # 2. Fallback to counting links in ANY Sources section (any level of header)
            if count == 0:
                # Matches ## Sources, # Sources, ### Sources etc.
                sources_match = re.search(r'(?i)#{1,6}\s*Sources\b([\s\S]*)', md)
                if sources_match:
                    sources_part = sources_match.group(1)
                    # Stop at next header if present
                    next_header_match = re.search(r'\n#{1,6}\s+', sources_part)
                    if next_header_match:
                        sources_part = sources_part[:next_header_match.start()]
                    
                    links = re.findall(r'\[.*?\]\(.*?\)', sources_part)
                    count = len(links)
            
            # 3. Recalculate Confidence (Canonical Logic)
            # High: 8+ sources
            # Medium: 3-7 sources
            # Low: 0-2 sources
            if count >= 8:
                new_conf = "High"
            elif count >= 3:
                new_conf = "Medium"
            else:
                new_conf = "Low"
            
            # 4. Extract Title if missing
            if not r.title:
                title_match = re.search(r'^#\s*(.*)', md)
                if title_match:
                    r.title = title_match.group(1).strip()
                    updated_count += 1

            # Optimization: only update if changed
            if r.source_count != count or r.confidence_level != new_conf:
                logger.debug(f"Queuing Fix Report [{r.id}]: {r.source_count}->{count}, {r.confidence_level}->{new_conf}")
                r.source_count = count
                r.confidence_level = new_conf
                updated_count += 1
                
        if updated_count > 0:
            await db.commit()
            logger.info(f"✅ Successfully backfilled {updated_count} reports.")
        else:
            logger.info("✨ No reports required backfilling.")

    except Exception as e:
        logger.error(f"Backfill failed: {e}")

if __name__ == "__main__":
    async def run_standalone():
        async with AsyncSessionLocal() as db:
            await backfill_reports(db)
    asyncio.run(run_standalone())
