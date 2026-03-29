
import asyncio
import os
import sys
import re
from sqlalchemy import select, func
from datetime import datetime, timezone, timedelta

# Add parent dir to path for imports
sys.path.append(os.getcwd())

from db.database import AsyncSessionLocal
from db.models import TrendSignal, Report, Item
from analysis.trend_engine import detect_trends
from article.report_job import run_report_generation

def normalize_label(l: str) -> str:
    if not l: return ""
    l = l.lower().strip()
    l = re.sub(r'\s+', ' ', l)
    return l.rstrip('.!?:;,')

async def final_verify():
    print("--- STARTING FINAL SURGE VERIFICATION ---")
    async with AsyncSessionLocal() as db:
        # 0. Check if we have items to trigger trends
        item_count = (await db.execute(select(func.count(Item.id)))).scalar()
        print(f"Total items in DB: {item_count}")
        if item_count < 10:
            print("[WARN] Low item count, trend detection might be thin.")

        # 1. Run detect_trends (Run A)
        print("\n[STEP 1] Running Trend Detection (Run A)...")
        await detect_trends(db)
        await db.commit()
        count_a = (await db.execute(select(func.count(TrendSignal.id)))).scalar()
        print(f"Trend signals after Run A: {count_a}")

        # 2. Run detect_trends (Run B - Stability Check)
        print("\n[STEP 2] Running Trend Detection (Run B)...")
        await detect_trends(db)
        await db.commit()
        count_b = (await db.execute(select(func.count(TrendSignal.id)))).scalar()
        print(f"Trend signals after Run B: {count_b}")
        
        delta = count_b - count_a
        print(f"DB Row Delta (Run B - Run A): {delta}")

        # 3. Trigger Fresh Report Generation
        print("\n[STEP 3] Generating Fresh Report...")
        path, status, msg = await run_report_generation(db, report_type="daily")
        print(f"Report Generation Status: {status}, Msg: {msg}")

        # 4. Inspect Report for Duplicates
        stmt = select(Report).order_by(Report.created_at.desc()).limit(1)
        r = (await db.execute(stmt)).scalar_one_or_none()
        
        if r:
            print(f"\n[STEP 4] Inspecting Report Content (ID: {r.id})...")
            content = r.content_markdown or ""
            
            # Find Emerging Surges section
            # Looking for patterns like "Themes: ..." or "Emerging Trends"
            # In our substack skeleton, they appear under "Themes" or specific headers.
            # But we can also look for normalized target labels in the text.
            
            # Since the user wants to confirm no duplicate labels exist:
            # We'll fetch the signals used in the report (last 24h) and check them directly.
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            signal_stmt = select(TrendSignal).where(TrendSignal.created_at >= since).order_by(TrendSignal.intensity_score.desc())
            report_signals = (await db.execute(signal_stmt)).scalars().all()
            
            print(f"Total signals available for report: {len(report_signals)}")
            
            seen_labels = {}
            duplicates_found = False
            
            for s in report_signals:
                n = normalize_label(s.target_label)
                if n in seen_labels:
                    print(f"[FAIL] DUPLICATE LABEL DETECTED: '{n}'")
                    print(f"  - Item 1: {seen_labels[n].trend_type} | Intensity: {seen_labels[n].intensity_score}")
                    print(f"  - Item 2: {s.trend_type} | Intensity: {s.intensity_score}")
                    duplicates_found = True
                else:
                    seen_labels[n] = s
            
            if not duplicates_found:
                print(f"[SUCCESS] No duplicate labels found among {len(seen_labels)} unique surge candidates.")
            
            print(f"Number of unique surge items: {len(seen_labels)}")
            print(f"Duplicates Exist: {'YES' if duplicates_found else 'NO'}")
        else:
            print("[FAIL] No report found.")

    print("\n--- FINAL VERIFICATION COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(final_verify())
