import sqlite3

db_path = "osint_platform.db"
tables = [
    "external_data_fetch_logs",
    "external_data_series",
    "external_industry_stats",
    "external_trade_flows",
    "external_observations"
]

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

for table in tables:
    try:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
        print(f"Dropped table: {table}")
    except Exception as e:
        print(f"Failed to drop {table}: {e}")

conn.commit()
conn.close()
