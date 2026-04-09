import sqlite3
import json
import re
import os

DB_PATH = 'osint_platform.db'
GENERIC_HEADERS = ["# summary of themes", "# executive summary", "# daily briefing", "# briefing", "summary of themes"]

def backfill_raw_sql():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, content_markdown, title, teaser_md FROM reports")
    rows = cursor.fetchall()
    
    updated = 0
    for row_id, content, current_title, current_teaser in rows:
        md = content or ""
        lines = md.split('\n')
        
        # --- Source Count ---
        count = 0
        evidence_match = re.search(r'<!--\s*EVIDENCE_JSON:\s*([\s\S]*?)\s*-->', md, re.IGNORECASE)
        if evidence_match:
            try:
                data = json.loads(evidence_match.group(1))
                count = len(data)
            except: pass
        
        if count == 0:
            sources_match = re.search(r'(?i)#{1,6}\s*Sources\b([\s\S]*)', md)
            if sources_match:
                sources_part = sources_match.group(1)
                next_header_match = re.search(r'\n#{1,6}\s+', sources_part)
                if next_header_match:
                    sources_part = sources_part[:next_header_match.start()]
                links = re.findall(r'\[.*?\]\(.*?\)', sources_part)
                count = len(links)
        
        # --- Confidence ---
        if count >= 8:
            new_conf = "High"
        elif count >= 3:
            new_conf = "Medium"
        else:
            new_conf = "Low"
            
        # --- Title ---
        new_title = current_title
        if not current_title or current_title.lower() in GENERIC_HEADERS:
            for line in lines:
                stripped = line.strip().lower()
                if line.startswith('# ') and stripped not in GENERIC_HEADERS:
                    new_title = line[2:].strip()
                    break
        
        # --- Teaser ---
        new_teaser = current_teaser
        if not current_teaser:
            teaser_lines = []
            for line in lines:
                clean = line.strip()
                if clean and not clean.startswith('#') and not clean.startswith('!') and not clean.startswith('[') and not clean.startswith('<!--'):
                    teaser_lines.append(clean)
                    if len(teaser_lines) >= 3:
                        break
            new_teaser = " ".join(teaser_lines)
            if len(new_teaser) > 280:
                new_teaser = new_teaser[:277] + "..."
        
        cursor.execute("""
            UPDATE reports 
            SET source_count = ?, confidence_level = ?, title = ?, teaser_md = ?
            WHERE id = ?
        """, (count, new_conf, new_title, new_teaser, row_id))
        updated += 1
        
    conn.commit()
    conn.close()
    print(f"Successfully backfilled {updated} reports via raw SQL.")

if __name__ == "__main__":
    backfill_raw_sql()
