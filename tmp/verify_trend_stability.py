
import asyncio
import os
import sys
from sqlalchemy import select, func
from datetime import datetime, timezone, timedelta

# Add parent dir to path for imports
sys.path.append(os.getcwd())

from db.database import AsyncSessionLocal
from db.models import TrendSignal
from analysis.trend_engine import detect_trends

async def verify_stability():
    print("--- STARTING STABILITY VERIFICATION ---")
    async with AsyncSessionLocal() as db:
        # 1. Initial Count
        count_start = (await db.execute(select(func.count(TrendSignal.id)))).scalar()
        print(f"Row count at start: {count_start}")
        
        # 2. RUN 1
        print("\n[RUN 1] Starting...")
        await detect_trends(db)
        await db.commit()
        count_after_1 = (await db.execute(select(func.count(TrendSignal.id)))).scalar()
        print(f"Row count after Run 1: {count_after_1}")
        
        # 3. RUN 2 (Immediately after)
        print("\n[RUN 2] Starting (should merge, not create)...")
        await detect_trends(db)
        await db.commit()
        count_after_2 = (await db.execute(select(func.count(TrendSignal.id)))).scalar()
        print(f"Row count after Run 2: {count_after_2}")
        
        # 4. Result
        diff = count_after_2 - count_after_1
        if diff == 0:
            print("\n[SUCCESS] Zero duplicate growth across runs. Stability confirmed.")
        else:
            print(f"\n[FAIL] Detected {diff} new rows in Run 2. Duplication guard still leaking.")
            # Check what was added
            stmt = select(TrendSignal).order_by(TrendSignal.created_at.desc()).limit(diff)
            leaked = (await db.execute(stmt)).scalars().all()
            for l in leaked:
                print(f"Leaked: {l.trend_type} | {l.target_label}")

    print("\n--- STABILITY VERIFICATION COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(verify_stability())
