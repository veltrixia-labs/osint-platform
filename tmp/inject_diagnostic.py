import sqlite3
import uuid

conn = sqlite3.connect('osint_platform.db')
cur = conn.cursor()

# Remove bad ID
cur.execute("DELETE FROM reports WHERE id='ai_semi_2026_premium_id'")

# Add diagnostics report
diag_id = str(uuid.uuid4()).replace('-', '')
cur.execute("INSERT INTO reports (id, report_type, topic_code, title, content_markdown, created_at, is_premium) VALUES (?, ?, ?, ?, ?, datetime('now'), ?)", 
            (diag_id, 'system_diagnostic', 'system', 'DEBUG DIAGNOSTIC', 'This should be hidden.', 0))

conn.commit()
conn.close()
print(f"Injected diagnostic report: {diag_id}")
