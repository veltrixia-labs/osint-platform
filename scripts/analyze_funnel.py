import sqlite3
import json

DB_PATH = "c:/RDTP project/Development/OSINT_analytics/osint_platform.db"

def analyze():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 1. Basic Counts
    cur.execute("SELECT event_type, COUNT(*) FROM analytics_events GROUP BY event_type")
    counts = dict(cur.fetchall())
    
    print("--- Funnel Analytics Report (Simulated) ---")
    print(f"Preview Views:  {counts.get('preview_view', 0)}")
    print(f"CTA Clicks:     {counts.get('cta_click', 0)}")
    print(f"Checkout Flows: {counts.get('checkout_flow', 0)}")
    print("-" * 30)
    
    # 2. Conversion Rates
    views = counts.get('preview_view', 1) # Avoid div by zero
    clicks = counts.get('cta_click', 0)
    checkouts = counts.get('checkout_flow', 0)
    
    ctr = (clicks / views) * 100
    checkout_rate = (checkouts / clicks) * 100 if clicks > 0 else 0
    overall_conv = (checkouts / views) * 100
    
    print(f"CTR (Preview -> CTA):    {ctr:.1f}%")
    print(f"Checkout Rate (CTA -> Pay): {checkout_rate:.1f}%")
    print(f"Overall Conversion:      {overall_conv:.1f}%")
    print("-" * 30)
    
    # 3. Visitor Path Validation
    # Identify visitors who reached CTA but not Preview (Anomaly check)
    cur.execute("""
        SELECT COUNT(DISTINCT json_extract(metadata_json, '$.visitor_id')) 
        FROM analytics_events 
        WHERE event_type='cta_click' 
        AND json_extract(metadata_json, '$.visitor_id') NOT IN (
            SELECT json_extract(metadata_json, '$.visitor_id') 
            FROM analytics_events 
            WHERE event_type='preview_view'
        )
    """)
    anomalies = cur.fetchone()[0]
    print(f"Path Anomalies (CTA without Preview): {anomalies}")
    
    # 4. Bottleneck Identification
    if ctr < 10:
        print("ALERT: High drop-off at Preview -> CTA (Low Engagement).")
    if checkout_rate < 20: # Example threshold
        print("ALERT: High drop-off at CTA -> Checkout (Friction in Pricing/Trust).")
        
    conn.close()

if __name__ == "__main__":
    analyze()
