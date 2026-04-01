import sqlite3
import os

def migrate():
    db_path = 'osint_platform.db'
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found. Skipping migration.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("Checking for Phase 3 (Intelligence Mapping) columns...")
    
    # 1. Update alert_logs
    for col in ["location_lat", "location_lng"]:
        try:
            cursor.execute(f"ALTER TABLE alert_logs ADD COLUMN {col} FLOAT")
            print(f"Added {col} to alert_logs.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"{col} already exists in alert_logs.")
            else:
                print(f"Error adding {col} to alert_logs: {e}")

    # 2. Update reports
    for col in ["location_lat", "location_lng"]:
        try:
            cursor.execute(f"ALTER TABLE reports ADD COLUMN {col} FLOAT")
            print(f"Added {col} to reports.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"{col} already exists in reports.")
            else:
                print(f"Error adding {col} to reports: {e}")

    conn.commit()
    conn.close()
    print("Phase 3 Schema update complete.")

if __name__ == "__main__":
    migrate()
