import asyncio
import os
import json
import logging
from sqlalchemy.future import select
from sqlalchemy import update
from db.database import SessionLocal
from db.models import Report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def diagnose_and_backfill():
    db = SessionLocal()
    try:
        logger.info("Starting report metadata diagnostics...")
        stmt = select(Report).order_by(Report.created_at.desc())
        result = await db.execute(stmt)
        reports = result.scalars().all()
        
        logger.info(f"Found {len(reports)} reports in DB.")
        
        fixed_count = 0
        for r in reports:
            print(f"\n--- Report ID: {r.id} ---")
            print(f"Title: {r.title}")
            print(f"Topic: {r.topic_code} | Date: {r.created_at}")
            print(f"Stored source_count: {r.source_count}")
            print(f"Stored confidence_level: {r.confidence_level}")
            
            # Analyze content for evidence
            md = r.content_markdown or ""
            count_from_json = 0
            
            # 1. Check EVIDENCE_JSON comment
            import re
            evidence_match = re.search(r'<!--\s*EVIDENCE_JSON:\s*([\s\S]*?)\s*-->', md)
            if evidence_match:
                try:
                    evidence_data = json.loads(evidence_match.group(1))
                    count_from_json = len(evidence_data)
                    print(f"Found {count_from_json} items in EVIDENCE_JSON")
                except Exception as e:
                    print(f"Error parsing EVIDENCE_JSON: {e}")
            
            # 2. Check Sources section if JSON missing
            if count_from_json == 0 and "# Sources" in md:
                sources_section = md.split("# Sources")[1]
                links = re.findall(r'\[(.*?)\]\((.*?)\)', sources_section)
                count_from_json = len(links)
                print(f"Found {count_from_json} links in Sources section")

            # Determine appropriate confidence
            if count_from_json >= 8:
                new_conf = "High"
            elif count_from_json >= 3:
                new_conf = "Medium"
            elif count_from_json > 0:
                new_conf = "Medium" # Better than Low if we have something
            else:
                new_conf = "Low"

            if r.source_count != count_from_json or r.confidence_level != new_conf:
                print(f"INCONSISTENCY DETECTED: DB({r.source_count}, {r.confidence_level}) vs Actual({count_from_json}, {new_conf})")
                r.source_count = count_from_json
                r.confidence_level = new_conf
                fixed_count += 1
                
        if fixed_count > 0:
            logger.info(f"Applying fixes for {fixed_count} reports...")
            await db.commit()
            logger.info("Database updated successfully.")
        else:
            logger.info("No inconsistencies found that required fixing.")

    except Exception as e:
        logger.error(f"Diagnostics failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(diagnose_and_backfill())
