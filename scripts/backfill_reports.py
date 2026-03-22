import asyncio
import os
import json
import logging
import re
from sqlalchemy.future import select
from db.database import SessionLocal
from db.models import Report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def backfill_reports():
    db = SessionLocal()
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
            
            # 1. Try to parse EVIDENCE_JSON
            evidence_match = re.search(r'<!--\s*EVIDENCE_JSON:\s*([\s\S]*?)\s*-->', md)
            if evidence_match:
                try:
                    data = json.loads(evidence_match.group(1))
                    count = len(data)
                except: pass
            
            # 2. Fallback to counting links in Sources section
            if count == 0 and "# Sources" in md:
                sources_part = md.split("# Sources")[-1]
                links = re.findall(r'\[.*?\]\(.*?\)', sources_part)
                count = len(links)
            
            # 3. Determine Confidence
            # If we had LLM success info we'd use it, otherwise use source density
            if count >= 8:
                new_conf = "High"
            elif count >= 3:
                new_conf = "Medium"
            elif count > 0:
                new_conf = "Medium"
            else:
                new_conf = "Low"
            
            # Optimization: only update if changed
            if r.source_count != count or r.confidence_level != new_conf:
                logger.info(f"Fixed Report [{r.id}]: {r.source_count}->{count}, {r.confidence_level}->{new_conf}")
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
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(backfill_reports())
