
import asyncio
import os
import sys
import re
from sqlalchemy import select, delete, func
from datetime import datetime, timezone, timedelta

# Add parent dir to path for imports
sys.path.append(os.getcwd())

from db.database import AsyncSessionLocal
from db.models import TrendSignal

def normalize_label(l: str) -> str:
    if not l: return ""
    l = l.lower().strip()
    l = re.sub(r'\s+', ' ', l)
    return l.rstrip('.!?:;,')

async def prune_duplicates():
    print("--- STARTING EMERGENCY TREND SIGNAL PRUNING ---")
    async with AsyncSessionLocal() as db:
        # 1. Count before
        total_count = (await db.execute(select(func.count(TrendSignal.id)))).scalar()
        print(f"Total signals before pruning: {total_count}")
        
        # 2. Fetch all signals from the last 72 hours (window for duplicates)
        since = datetime.now(timezone.utc) - timedelta(hours=72)
        stmt = select(TrendSignal).where(TrendSignal.created_at >= since).order_by(TrendSignal.created_at.desc())
        signals = (await db.execute(stmt)).scalars().all()
        
        # 3. Identify duplicates
        seen_keys = {} # key: (type, label) -> best_signal
        to_keep = set()
        to_delete = []
        
        for s in signals:
            n_label = normalize_label(s.target_label)
            key = (s.trend_type, n_label)
            
            if key in seen_keys:
                existing = seen_keys[key]
                # Decision: Keep the one with higher intensity or later timestamp
                # Since we ordered DESC, 'existing' is newer.
                # But we also want to keep max intensity.
                if s.intensity_score > existing.intensity_score:
                    # Current one is better, swap
                    to_delete.append(existing.id)
                    seen_keys[key] = s
                    to_keep.add(s.id)
                    if existing.id in to_keep: to_keep.remove(existing.id)
                else:
                    to_delete.append(s.id)
            else:
                seen_keys[key] = s
                to_keep.add(s.id)
        
        print(f"Signals identified for keeping: {len(to_keep)}")
        print(f"Signals identified for deletion: {len(to_delete)}")
        
        # 4. Perform Deletion in batches
        if to_delete:
            batch_size = 500
            deleted_total = 0
            for i in range(0, len(to_delete), batch_size):
                batch = to_delete[i:i+batch_size]
                await db.execute(delete(TrendSignal).where(TrendSignal.id.in_(batch)))
                deleted_total += len(batch)
                print(f"Pruned {deleted_total}/{len(to_delete)}...")
            
            await db.commit()
            print(f"Successfully committed deletion of {deleted_total} duplicates.")
        
        # 5. Final Count
        final_count = (await db.execute(select(func.count(TrendSignal.id)))).scalar()
        print(f"Total signals after pruning: {final_count}")

    print("\n--- PRUNING COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(prune_duplicates())
