
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
    print("--- STARTING 4-TIER REDESIGN VERIFICATION (LIVE REGENERATION) ---")
    
    async with AsyncSessionLocal() as db:
        # 1. Cleanup old verification data
        await db.execute(delete(Item).where(Item.source_name == "Verification Probe"))
        await db.commit()

        # 2. Inject fresh test data
        print("Injecting fresh intelligence signals...")
        for i in range(5):
            test_url = f"http://verification.internal/signal-{uuid.uuid4().hex[:8]}"
            dummy_item = Item(
                dedup_key=f"verify-{uuid.uuid4().hex}",
                source_name="Verification Probe",
                source_url=test_url,
                title=f"Verification Test Signal {i}: Global Semiconductor Logistics",
                summary="Systemic monitoring of high-fidelity logistics bottlenecks in East Asian semiconductor hubs.",
                type="news",
                published_at=datetime.now(timezone.utc),
                rough_category="technology"
            )
            db.add(dummy_item)
        await db.commit()
        
        # 3. Test DAILY (Free, No LLM)
        print("\nTEST 1: DAILY Generation (Goal: Free, No LLM)")
        path, status, msg = await run_report_generation(db, report_type="daily")
        print(f"Status: {status}, Msg: {msg}")
        
        stmt = select(Report).where(Report.report_type == ReportType.DAILY.value).order_by(Report.created_at.desc()).limit(1)
        r = (await db.execute(stmt)).scalar_one_or_none()
        if r:
            print(f"[VERIFY] Title: {r.title}")
            print(f"[VERIFY] Plan Required: {r.plan_required}")
            if r.plan_required == "free":
                print("[OK] Daily tier mapping: PASS")
            else:
                print("[FAIL] Daily tier mapping: FAIL")
        
        # 4. Test WEEKLY (Pro, Lightweight LLM)
        print("\nTEST 2: WEEKLY Generation (Goal: Pro, LLM Attempted)")
        path, status, msg = await run_report_generation(db, report_type="weekly")
        print(f"Status: {status}, Msg: {msg}")
        
        stmt = select(Report).where(Report.report_type == ReportType.WEEKLY.value).order_by(Report.created_at.desc()).limit(1)
        r = (await db.execute(stmt)).scalar_one_or_none()
        if r:
            print(f"[VERIFY] Title: {r.title}")
            print(f"[VERIFY] Plan Required: {r.plan_required}")
            if r.plan_required == "pro":
                print("[OK] Weekly tier mapping: PASS")
            else:
                print("[FAIL] Weekly tier mapping: FAIL")

        # 5. Test MONTHLY (Experts, Full LLM)
        print("\nTEST 3: MONTHLY Generation (Goal: Experts, Full LLM)")
        path, status, msg = await run_report_generation(db, report_type="monthly")
        print(f"Status: {status}, Msg: {msg}")
        
        stmt = select(Report).where(Report.report_type == ReportType.MONTHLY.value).order_by(Report.created_at.desc()).limit(1)
        r = (await db.execute(stmt)).scalar_one_or_none()
        if r:
            print(f"[VERIFY] Title: {r.title}")
            print(f"[VERIFY] Plan Required: {r.plan_required}")
            if r.plan_required == "experts":
                print("[OK] Monthly tier mapping: PASS")
            else:
                print("[FAIL] Monthly tier mapping: FAIL")
            
            if r.content_markdown and "Scenario Analysis" in r.content_markdown:
                print("[OK] Monthly content richness: PASS")
            else:
                print("[WARN] Monthly content richness: LLM might have fallen back, check logs.")

        # Cleanup
        print("\nCleaning up verification data...")
        await db.execute(delete(Item).where(Item.source_name == "Verification Probe"))
        await db.commit()

    print("\n--- 4-TIER VERIFICATION COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(verify())
