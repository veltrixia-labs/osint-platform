import sqlite3
import os

db_path = "osint_platform.db"

def migrate():
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found. Skipping migration (it will be created on first run).")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("Checking for AnalystProfile migrations...")
    
    # 1. Check if email column exists
    cursor.execute("PRAGMA table_info(analyst_profiles)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "email" not in columns:
        print("Adding 'email' column to analyst_profiles...")
        # Step 1: Add column without UNIQUE (SQLite limitation)
        cursor.execute("ALTER TABLE analyst_profiles ADD COLUMN email TEXT")

    if "is_email_verified" not in columns:
        print("Adding 'is_email_verified' column to analyst_profiles...")
        cursor.execute("ALTER TABLE analyst_profiles ADD COLUMN is_email_verified BOOLEAN DEFAULT 0")

    # 2. Backfill existing users (placeholder emails)
    cursor.execute("SELECT id, telegram_chat_id FROM analyst_profiles WHERE email IS NULL")
    users = cursor.fetchall()
    for uid, chat_id in users:
        placeholder = f"{chat_id or uid}@temporary.veltrixia.com"
        print(f"Backfilling user {uid} with email {placeholder}")
        cursor.execute("UPDATE analyst_profiles SET email = ? WHERE id = ?", (placeholder, uid))

    # 3. Create UNIQUE INDEX (standard way to add UNIQUE to existing column in SQLite)
    print("Creating UNIQUE INDEX on email...")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_analyst_email ON analyst_profiles(email)")

    conn.commit()
    conn.close()
    print("Migration completed successfully.")

if __name__ == "__main__":
    migrate()
