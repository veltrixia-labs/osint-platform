import sqlite3
import os

def check_db():
    conn = sqlite3.connect('osint_platform.db')
    cursor = conn.cursor()
    
    # 1. Check all types
    cursor.execute("SELECT DISTINCT report_type FROM reports")
    types = cursor.fetchall()
    print(f"Report types in DB: {[t[0] for t in types]}")
    
    # 2. Check counts for diagnostics
    cursor.execute("SELECT count(*) FROM reports WHERE report_type LIKE 'system_diagnostic%'")
    diag_count = cursor.fetchone()[0]
    print(f"Diagnostic reports count (LIKE 'system_diagnostic%'): {diag_count}")
    
    # 3. Check exact match count
    cursor.execute("SELECT count(*) FROM reports WHERE report_type = 'system_diagnostic'")
    exact_diag_count = cursor.fetchone()[0]
    print(f"Diagnostic reports count (EXACT): {exact_diag_count}")
    
    # 4. Check normal reports
    cursor.execute("SELECT count(*) FROM reports WHERE report_type NOT LIKE 'system_diagnostic%'")
    normal_count = cursor.fetchone()[0]
    print(f"Normal reports count: {normal_count}")
    
    if normal_count > 0:
        cursor.execute("SELECT report_type, topic_code, title FROM reports WHERE report_type NOT LIKE 'system_diagnostic%' LIMIT 5")
        rows = cursor.fetchall()
        for r in rows:
            print(f" - [{r[0]}] {r[1]}: {r[2]}")
            
    conn.close()

if __name__ == "__main__":
    check_db()
