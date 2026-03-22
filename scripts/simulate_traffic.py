import urllib.request
import json
import uuid
import time
import random

BASE_URL = "http://localhost:8000"
REPORT_ID = "6ba7b8109dad11d180b400c04fd430c8" # Premium Report

def log_event(event_type, visitor_id, metadata=None):
    url = f"{BASE_URL}/api/analytics/event"
    data = {
        "event_type": event_type,
        "report_id": REPORT_ID,
        "metadata_json": {
            "visitor_id": visitor_id,
            "utm_source": "threads_day1",
            **(metadata or {})
        }
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Error logging {event_type} for {visitor_id}: {e}")
        return False

def run_simulation():
    print(f"Starting simulation: 100 visitors...")
    visitors = [str(uuid.uuid4()) for _ in range(100)]
    
    # 1. 100 Preview Views
    print("Generating 100 preview_view events...")
    for vid in visitors:
        log_event("preview_view", vid)
    
    # 2. 20 CTA Clicks (from 100 visitors)
    print("Generating 20 cta_click events...")
    cta_visitors = random.sample(visitors, 20)
    for vid in cta_visitors:
        log_event("cta_click", vid)
        
    # 3. 5 Checkout Flow (from 20 CTA visitors)
    # Note: Using 'checkout_flow' as requested. We assume the backend allows it for verification purposes.
    # In api/main.py, unauth can only log preview_view and cta_click. 
    # For simulation, we might need a mock auth or temporarily allow it.
    print("Generating 5 checkout_flow events...")
    checkout_visitors = random.sample(cta_visitors, 5)
    for vid in checkout_visitors:
        # Since 'checkout_flow' is not in 'allowed_unauth', we expect 403 unless we're 'logged in'.
        # For this system verification, let's see how it behaves.
        log_event("checkout_flow", vid)

    print("Simulation complete.")

if __name__ == "__main__":
    run_simulation()
