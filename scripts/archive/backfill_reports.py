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
        GENERIC_HEADERS = ["# summary of themes", "# executive summary", "# daily briefing", "# briefing", "summary of themes"]
        
        for r in reports:
            md = r.content_markdown or ""
            lines = md.split('\n')
            
            # --- Source Count ---
            count = 0
            evidence_match = re.search(r'<!--\s*EVIDENCE_JSON:\s*([\s\S]*?)\s*-->', md, re.IGNORECASE)
            if evidence_match:
                try:
                    data = json.loads(evidence_match.group(1))
                    count = len(data)
                except: pass
            
            if count == 0:
                sources_match = re.search(r'(?i)#{1,6}\s*Sources\b([\s\S]*)', md)
                if sources_match:
                    sources_part = sources_match.group(1)
                    next_header_match = re.search(r'\n#{1,6}\s+', sources_part)
                    if next_header_match:
                        sources_part = sources_part[:next_header_match.start()]
                    links = re.findall(r'\[.*?\]\(.*?\)', sources_part)
                    count = len(links)
            
            # --- Confidence ---
            if count >= 8:
                new_conf = "High"
            elif count >= 3:
                new_conf = "Medium"
            else:
                new_conf = "Low"
            
            # --- Title ---
            new_title = r.title
            if not r.title or r.title.lower() in GENERIC_HEADERS:
                for line in lines:
                    stripped = line.strip().lower()
                    if line.startswith('# ') and stripped not in GENERIC_HEADERS:
                        new_title = line[2:].strip()
                        break
            
            # --- Teaser ---
            new_teaser = r.teaser_md
            if not r.teaser_md:
                teaser_lines = []
                for line in lines:
                    clean = line.strip()
                    if clean and not clean.startswith('#') and not clean.startswith('!') and not clean.startswith('[') and not clean.startswith('<!--'):
                        teaser_lines.append(clean)
                        if len(teaser_lines) >= 3:
                            break
                new_teaser = " ".join(teaser_lines)
                if len(new_teaser) > 280:
                    new_teaser = new_teaser[:277] + "..."

            # Optimization: only update if changed
            changed = False
            if r.source_count != count:
                r.source_count = count
                changed = True
            if r.confidence_level != new_conf:
                r.confidence_level = new_conf
                changed = True
            if r.title != new_title:
                r.title = new_title
                changed = True
            if r.teaser_md != new_teaser:
                r.teaser_md = new_teaser
                changed = True
                
            if changed:
                logger.debug(f"Queuing Fix Report [{r.id}]: {r.title}")
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
