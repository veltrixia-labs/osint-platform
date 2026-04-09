import sqlite3
import psycopg2
import uuid
import json
import os
import random
from datetime import datetime

# Configuration
SQLITE_PATH = "osint.db"
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://postgres:postgres@localhost/osint_platform")

PRIORITY_TABLES = ["analyst_profiles", "alert_logs", "alert_deliveries", "reports", "trend_signals"]

def get_sqlite_rows(table_name):
    conn = sqlite3.connect(SQLITE_PATH)
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    # Get column names
    cursor.execute(f"PRAGMA table_info({table_name})")
    cols = [c[1] for c in cursor.fetchall()]
    conn.close()
    return rows, cols

def get_pg_row(table_name, pk_col, pk_val):
    conn = psycopg2.connect(POSTGRES_DSN)
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name} WHERE {pk_col} = %s", (pk_val,))
    row = cursor.fetchone()
    # Get column names
    cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position", (table_name,))
    cols = [r[0] for r in cursor.fetchall()]
    conn.close()
    return row, cols

def compare_values(v1, v2, col_name):
    # Handle UUID string comparison
    if isinstance(v1, str) and len(v1) == 36:
        try:
            if uuid.UUID(v1) == uuid.UUID(str(v2)):
                return True
        except:
            pass
    
    # Handle JSON comparison
    if col_name.endswith("_json") or col_name.startswith("watch_") or col_name == "supporting_clusters":
        try:
            j1 = json.loads(v1) if isinstance(v1, str) else v1
            j2 = v2 # Postgres JSONB comes back as dict/list
            if j1 == j2:
                return True
        except:
            pass

    # Basic comparison
    return str(v1) == str(v2)

def verify():
    if not os.path.exists(SQLITE_PATH):
        print("SQLite file not found.")
        return

    print("=== Migration Verification Start ===")
    
    for table in PRIORITY_TABLES:
        sqlite_rows, sqlite_cols = get_sqlite_rows(table)
        
        # 1. Count check
        pg_conn = psycopg2.connect(POSTGRES_DSN)
        pg_cursor = pg_conn.cursor()
        pg_cursor.execute(f"SELECT count(*) FROM {table}")
        pg_count = pg_cursor.fetchone()[0]
        pg_conn.close()

        print(f"\nTable: {table}")
        print(f"  SQLite Count: {len(sqlite_rows)}")
        print(f"  Postgres Count: {pg_count}")
        
        if len(sqlite_rows) != pg_count:
            print(f"  [ERROR] Count mismatch in {table}!")
        else:
            print(f"  [OK] Count match.")

        # 2. Sample Verification
        if not sqlite_rows:
            continue

        sample_size = max(10, int(len(sqlite_rows) * 0.05))
        sample_size = min(sample_size, len(sqlite_rows))
        sample_rows = random.sample(sqlite_rows, sample_size)
        
        print(f"  Verifying {sample_size} random samples (5% rule)...")
        
        pk_idx = 0 # Assuming 'id' is always first
        pk_col = sqlite_cols[0]
        
        errors = 0
        for s_row in sample_rows:
            pk_val = s_row[pk_idx]
            p_row, pg_cols = get_pg_row(table, pk_col, pk_val)
            
            if not p_row:
                print(f"    [FAIL] Row with PK {pk_val} not found in Postgres.")
                errors += 1
                continue
            
            # Map SQLite values to PG names
            for i, col in enumerate(sqlite_cols):
                sv = s_row[i]
                # Find corresponding index in PG (order might differ)
                try:
                    pi = pg_cols.index(col)
                    pv = p_row[pi]
                    if not compare_values(sv, pv, col):
                        print(f"    [FAIL] Data mismatch in {table}:{col} for PK {pk_val}")
                        print(f"      SQLite: {sv}")
                        print(f"      Postgres: {pv}")
                        errors += 1
                except ValueError:
                    continue # Column might not exist in PG or renamed

        if errors == 0:
            print(f"  [OK] All {sample_size} samples verified.")
        else:
            print(f"  [ERROR] {errors} data mismatches found in samples!")

    print("\n=== Verification Complete ===")

if __name__ == "__main__":
    verify()
