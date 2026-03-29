
import asyncio
import os
import sys
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
import json

# Add parent dir to path for imports
sys.path.append(os.getcwd())

from db.database import AsyncSessionLocal
from db.models import TrendSignal

async def audit_data():
    print("--- STARTING TREND SIGNAL DATA AUDIT ---")
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=48)
        
        stmt = select(TrendSignal).where(TrendSignal.created_at >= since).order_by(TrendSignal.created_at.desc())
        signals = (await db.execute(stmt)).scalars().all()
        
        print(f"Total signals found (48h): {len(signals)}")
        
        # Check for duplicates by label and type
        seen = {}
        duplicates = []
        
        for s in signals:
            # key: (type, label, cluster_id)
            cid = (s.metrics_json or {}).get("cluster_id")
            key = (s.trend_type, s.target_label.lower().strip(), str(cid) if cid else None)
            
            if key in seen:
                duplicates.append((s, seen[key]))
            else:
                seen[key] = s
        
        print(f"Total duplicate sets identified: {len(duplicates)}")
        
        if duplicates:
            print("\nDUPLICATE SAMPLES:")
            for i, (new, old) in enumerate(duplicates[:10]):
                print(f"\n--- Set {i+1} ---")
                print(f"Type: {new.trend_type}")
                print(f"Label: {new.target_label}")
                print(f"Cluster ID: {(new.metrics_json or {}).get('cluster_id')}")
                print(f"Created At: {new.created_at}")
                print(f"Intensity: {new.intensity_score} vs Previous: {old.intensity_score}")
                print(f"Description match: {new.description == old.description}")
                # print(f"Metrics match: {json.dumps(new.metrics_json) == json.dumps(old.metrics_json)}")
        else:
            print("No identical (type, label, cluster_id) duplicates found in DB.")
            
            # Check for close matches (labels that are very similar)
            print("\nChecking for near-duplicates (Label overlap)...")
            seen_labels = {}
            for s in signals:
                l = s.target_label.lower().strip()
                if l in seen_labels:
                    print(f"Near Dup: '{l}' (Type: {s.trend_type}, ID: {s.id})")
                    seen_labels[l].append(s)
                else:
                    seen_labels[l] = [s]

    print("\n--- AUDIT COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(audit_data())
