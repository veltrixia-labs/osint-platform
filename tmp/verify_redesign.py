
import asyncio
import os
import sys
from sqlalchemy import select, delete
from datetime import datetime, timezone, timedelta
import uuid

# Add parent dir to path for imports
sys.path.append(os.getcwd())

from db.database import AsyncSessionLocal
from db.models import Report, Item
from article.report_job import run_report_generation
from db.enums import PlanTier, ReportType

async def verify():
    print("--- STARTING REDESIGN VERIFICATION (LIVE GENERATION) ---")
    
    async with AsyncSessionLocal() as db:
        # 1. Create a dummy item for today
        print("Creating dummy intelligence signal...")
        test_url = f"http://verification.internal/signal-{uuid.uuid4().hex[:8]}"
        dummy_item = Item(
            dedup_key=f"verify-{uuid.uuid4().hex}",
            source_name="Verification Probe",
            source_url=test_url,
            title="Taiwan Semiconductor Chain Expansion in Arizona",
            summary="New high-fidelity signal detected regarding US-based logic production capacity expansion for Q3-Q4 2026.",
            type="news",
            published_at=datetime.now(timezone.utc),
            rough_category="technology"
        )
        db.add(dummy_item)
        await db.commit()
        
        # 2. Trigger a DAILY generation (should be LLM-free)
        print("Triggering DAILY generation...")
        path, status, msg = await run_report_generation(db, report_type="daily")
        print(f"Generation Status: {status}, Msg: {msg}")

        # 3. Check Database for THAT report
        print("\nVerifying the generated report...")
        stmt = select(Report).where(Report.report_type == ReportType.DAILY.value).order_by(Report.created_at.desc()).limit(1)
        res = await db.execute(stmt)
        r = res.scalar_one_or_none()
        
        if not r:
            print("Failed to retrieve the generated report.")
            return

        print(f"Report ID: {r.id}")
        print(f"Type: {r.report_type}")
        print(f"Plan Required: {r.plan_required}")
        print(f"Title: {r.title}")
        
        # Title Format Check
        title_str = r.title or ""
        if title_str.startswith("Themes:") and "|" in title_str and "Intelligence" in title_str:
            print("[OK] Title Format: PASS")
        else:
            print("[FAIL] Title Format: FAIL (Detected: " + str(title_str) + ")")

        # LLM Isolation Check
        if r.plan_required == "free":
            print("[OK] Plan Mapping (free): PASS")
        else:
            print("[FAIL] Plan Mapping: FAIL")
            
        # 4. Cleanup
        print("\nCleaning up verification data...")
        await db.execute(delete(Item).where(Item.source_url == test_url))
        await db.commit()

    print("\n--- VERIFICATION COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(verify())
