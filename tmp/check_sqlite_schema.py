import sqlite3
import sys

db_path = "osint_platform.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(reports)")
cols = cursor.fetchall()
for col in cols:
    print(col)
conn.close()
