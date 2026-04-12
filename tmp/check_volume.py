import sqlite3
import os

db_path = r"c:\RDTP project\Development\OSINT_analytics\osint_platform.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT severity, COUNT(*) FROM alert_logs GROUP BY severity;")
    rows = cursor.fetchall()
    print("Alert Volume by Severity:")
    for row in rows:
        print(f"  {row[0]}: {row[1]}")
    conn.close()
else:
    print(f"DB not found at {db_path}")
