import sqlite3
import json
import uuid
from datetime import datetime

conn = sqlite3.connect('osint_platform.db')
cur = conn.cursor()

# Add a zero-domain alert
alert_id = str(uuid.uuid4())
meta = {"domain_count": 0, "evidence_list": []}
cur.execute("INSERT INTO alert_logs (id, severity, target_label, topic, trigger_type, intelligence_score, intensity, triggered_at, metadata_json, suppressed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
            (alert_id, 'LOW', 'EMPTY SIGNAL TEST', 'global', 'pattern_match', 0.5, 0.5, datetime.now(), json.dumps(meta), 0))

conn.commit()
conn.close()
print(f"Injected zero-domain alert: {alert_id}")
