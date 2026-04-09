import sqlite3
import psycopg2
from psycopg2.extras import execute_values
import uuid
import json
import os
from datetime import datetime

# Configuration (Defaults for local dev)
SQLITE_PATH = "osint.db"
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://postgres:postgres@localhost/osint_platform")

def migrate_table(sqlite_conn, pg_conn, table_name, columns, uuid_cols=None, json_cols=None):
    print(f"Migrating table: {table_name}...")
    cursor_sqlite = sqlite_conn.cursor()
    cursor_pg = pg_conn.cursor()

    # Fetch all data from SQLite
    cursor_sqlite.execute(f"SELECT * FROM {table_name}")
    rows = cursor_sqlite.fetchall()
    
    if not rows:
        print(f"  No data in {table_name}.")
        return

    # Process rows for Postgres compatibility
    processed_rows = []
    for row in rows:
        new_row = list(row)
        # Handle UUID conversion
        if uuid_cols:
            for col_idx in uuid_cols:
                if new_row[col_idx]:
                    new_row[col_idx] = str(uuid.UUID(new_row[col_idx]))
        
        # Handle JSON conversion
        if json_cols:
            for col_idx in json_cols:
                if new_row[col_idx]:
                    # Ensure it's valid JSON for JSONB
                    if isinstance(new_row[col_idx], str):
                        try:
                            new_row[col_idx] = json.dumps(json.loads(new_row[col_idx]))
                        except:
                            pass
        
        processed_rows.append(tuple(new_row))

    # Construct INSERT query
    placeholders = ",".join(["%s"] * len(columns))
    cols_str = ",".join(columns)
    insert_query = f"INSERT INTO {table_name} ({cols_str}) VALUES %s ON CONFLICT DO NOTHING"

    execute_values(cursor_pg, insert_query, processed_rows)
    pg_conn.commit()
    print(f"  Successfully migrated {len(rows)} rows to {table_name}.")

def main():
    if not os.path.exists(SQLITE_PATH):
        print(f"SQLite file not found at {SQLITE_PATH}")
        return

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    try:
        pg_conn = psycopg2.connect(POSTGRES_DSN)
    except Exception as e:
        print(f"Could not connect to Postgres: {e}")
        return

    # Define table mappings
    # (Table Name, Columns, UUID indices, JSON indices)
    tables = [
        ("items", 
         ["id", "title", "content", "url", "source", "published_at", "normalized_content", "entities", "category", "cluster_id", "intensity_score", "risk_score", "processed_at"],
         None, [7]),
        ("reports",
         ["id", "title", "summary", "full_markdown", "category", "metadata_json", "substack_slug", "substack_draft_url", "substack_published_url", "substack_post_status", "substack_post_id", "created_at"],
         [0], [5]),
        ("external_posts",
         ["id", "platform", "external_id", "content_preview", "url", "related_report_id", "posted_at", "metrics"],
         [0, 5], [7]),
        ("risk_headlining",
         ["id", "cluster_id", "headline_en", "headline_jp", "impact_score", "geopolitical_context", "last_updated"],
         [0], None),
        ("trend_signals",
         ["id", "topic", "pattern_name", "intensity", "summary", "supporting_clusters", "detected_at"],
         [0], [5]),
        ("alert_logs",
         ["id", "trigger_type", "severity", "topic", "message", "feedback_score", "related_report_id", "intelligence_score", "suppressed", "metadata_json", "created_at"],
         [0, 6], [9]),
        ("analyst_profiles",
         ["id", "telegram_chat_id", "hashed_password", "user_role", "watch_keywords", "watch_entities", "watch_sectors", "min_severity_threshold", "min_intelligence_threshold", "is_active", "created_at"],
         [0], [4, 5, 6]),
        ("alert_deliveries",
         ["id", "alert_log_id", "analyst_id", "status", "relevance_score", "suppression_reason", "delivered_at"],
         [0, 1, 2], None)
    ]

    for table_name, cols, uuids, jsons in tables:
        migrate_table(sqlite_conn, pg_conn, table_name, cols, uuids, jsons)

    sqlite_conn.close()
    pg_conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    main()
