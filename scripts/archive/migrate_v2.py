import sqlite3
import os

def migrate():
    db_path = 'osint_platform.db'
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found. Skipping migration.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("Checking for Phase 2 columns in alert_logs...")
    
    # Add fidelity_score
    try:
        cursor.execute("ALTER TABLE alert_logs ADD COLUMN fidelity_score FLOAT DEFAULT 0.0")
        print("Added fidelity_score to alert_logs.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("fidelity_score already exists.")
        else:
            print(f"Error adding fidelity_score: {e}")

    # Add is_high_fidelity
    try:
        cursor.execute("ALTER TABLE alert_logs ADD COLUMN is_high_fidelity BOOLEAN DEFAULT 0")
        print("Added is_high_fidelity to alert_logs.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("is_high_fidelity already exists.")
        else:
            print(f"Error adding is_high_fidelity: {e}")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
