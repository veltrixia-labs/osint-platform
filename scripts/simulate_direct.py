import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
import random

DB_PATH = "c:/RDTP project/Development/OSINT_analytics/osint_platform.db"
REPORT_ID = "6ba7b8109dad11d180b400c04fd430c8"

def simulate_direct():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Clear existing
    cur.execute("DELETE FROM analytics_events")
    
    now = datetime.now(timezone.utc)
    visitors = [str(uuid.uuid4()) for _ in range(100)]
    
    events = []
    
    # 1. 100 Preview Views
    for vid in visitors:
        events.append((
            str(uuid.uuid4()),
            "preview_view",
            REPORT_ID,
            None, # user_id
            json.dumps({"visitor_id": vid, "utm_source": "threads_day1"}),
            (now - timedelta(minutes=random.randint(60, 120))).isoformat()
        ))
        
    # 2. 20 CTA Clicks
    cta_visitors = random.sample(visitors, 20)
    for vid in cta_visitors:
        events.append((
            str(uuid.uuid4()),
            "cta_click",
            REPORT_ID,
            None,
            json.dumps({"visitor_id": vid, "utm_source": "threads_day1"}),
            (now - timedelta(minutes=random.randint(30, 60))).isoformat()
        ))
        
    # 3. 5 Checkout Flow
    checkout_visitors = random.sample(cta_visitors, 5)
    for vid in checkout_visitors:
        events.append((
            str(uuid.uuid4()),
            "checkout_flow",
            REPORT_ID,
            None,
            json.dumps({"visitor_id": vid, "utm_source": "threads_day1"}),
            (now - timedelta(minutes=random.randint(5, 10))).isoformat()
        ))
        
    print(f"Injecting {len(events)} events...")
    cur.executemany("""
        INSERT INTO analytics_events (id, event_type, report_id, user_id, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, events)
    
    conn.commit()
    conn.close()
    print("Direct Injection Complete.")

import json
if __name__ == "__main__":
    simulate_direct()
