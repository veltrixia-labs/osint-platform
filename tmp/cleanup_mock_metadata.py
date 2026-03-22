import sqlite3

DB_PATH = "c:\\RDTP project\\Development\\OSINT_analytics\\osint_platform.db"

def cleanup():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Remove the EVIDENCE_JSON comments from all reports
    cur.execute("SELECT id, content_markdown FROM reports WHERE content_markdown LIKE '%<!-- EVIDENCE_JSON:%'")
    rows = cur.fetchall()
    
    for report_id, content in rows:
        # Regex to remove the comment
        import re
        new_content = re.sub(r'<!--\s*EVIDENCE_JSON:\s*([\s\S]*?)\s*-->', '', content).strip()
        cur.execute("UPDATE reports SET content_markdown = ? WHERE id = ?", (new_content, report_id))
        print(f"Cleaned metadata from report {report_id}")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    cleanup()
