import sqlite3

DB_PATH = "c:/RDTP project/Development/OSINT_analytics/osint_platform.db"

def migrate_schema():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    try:
        # 1. Update reports table
        print("Migrating reports table...")
        columns_to_add_reports = [
            ("is_premium", "BOOLEAN DEFAULT 0"),
            ("source_count", "INTEGER DEFAULT 0"),
            ("confidence_level", "TEXT DEFAULT 'Low'")
        ]
        
        for col_name, col_def in columns_to_add_reports:
            try:
                cur.execute(f"ALTER TABLE reports ADD COLUMN {col_name} {col_def}")
                print(f"Added column {col_name} to reports.")
            except sqlite3.OperationalError:
                print(f"Column {col_name} already exists in reports.")

        # 2. Update analyst_profiles table
        print("\nMigrating analyst_profiles table...")
        columns_to_add_profiles = [
            ("subscription_tier", "TEXT DEFAULT 'free'"),
            ("subscription_expires_at", "TEXT"),
            ("stripe_customer_id", "TEXT"),
            ("stripe_subscription_id", "TEXT")
        ]

        for col_name, col_def in columns_to_add_profiles:
            try:
                cur.execute(f"ALTER TABLE analyst_profiles ADD COLUMN {col_name} {col_def}")
                print(f"Added column {col_name} to analyst_profiles.")
            except sqlite3.OperationalError:
                print(f"Column {col_name} already exists in analyst_profiles.")

        conn.commit()
        print("\nSchema migration successful.")
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_schema()
