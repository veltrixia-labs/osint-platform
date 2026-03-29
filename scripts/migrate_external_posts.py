
import sqlite3
import os
import re
import uuid

def normalize_theme(text: str) -> str:
    if not text: return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text) # Strip punctuation
    text = " ".join(text.split()) # Normalize spacing
    return text.strip()

def migrate():
    db_path = "osint_platform.db"
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("--- MIGRATING external_posts ---")

    # 1. Check columns
    cursor.execute("PRAGMA table_info(external_posts)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if "category" not in columns:
        print("Adding 'category' column...")
        cursor.execute("ALTER TABLE external_posts ADD COLUMN category TEXT")
    
    if "normalized_theme" not in columns:
        print("Adding 'normalized_theme' column...")
        cursor.execute("ALTER TABLE external_posts ADD COLUMN normalized_theme TEXT")

    # 2. Backfill
    print("Backfilling existing rows...")
    cursor.execute("""
        SELECT ep.id, r.topic_code, r.title 
        FROM external_posts ep
        JOIN reports r ON ep.report_id = r.id
        WHERE ep.normalized_theme IS NULL OR ep.category IS NULL
    """)
    rows = cursor.fetchall()
    
    updated_count = 0
    for row_id, topic, title in rows:
        norm = normalize_theme(title)
        cursor.execute("""
            UPDATE external_posts 
            SET category = ?, normalized_theme = ? 
            WHERE id = ?
        """, (topic, norm, row_id))
        updated_count += 1

    conn.commit()
    conn.close()
    print(f"Migration complete. Updated {updated_count} rows.")

if __name__ == "__main__":
    migrate()
