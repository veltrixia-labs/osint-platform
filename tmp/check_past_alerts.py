import sqlite3
import os
import json

db_path = r"c:\RDTP project\Development\OSINT_analytics\osint_platform.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Get the last 5 alerts
    cursor.execute("SELECT id, target_label, topic, severity, triggered_at, metadata_json FROM alert_logs ORDER BY triggered_at DESC LIMIT 5;")
    rows = cursor.fetchall()
    print("Recent Alerts Metadata Check:")
    for row in rows:
        meta = json.loads(row[5]) if row[5] else {}
        impacts = meta.get("cascading_impacts", [])
        print(f"  ID: {row[0]} | Title: {row[1]} | Severity: {row[3]} | Time: {row[4]}")
        print(f"  Impacts Count: {len(impacts)}")
        if impacts:
            print(f"  Source: {impacts[0].get('source')}")
    conn.close()
else:
    print("DB not found")
