import sqlite3

def verify_table():
    conn = sqlite3.connect("osint_platform.db")
    cursor = conn.cursor()
    
    print("Table Info (bea_nipa_observations):")
    cursor.execute("PRAGMA table_info(bea_nipa_observations);")
    for row in cursor.fetchall():
        print(f"  {row}")
        
    print("\nIndex List (bea_nipa_observations):")
    cursor.execute("PRAGMA index_list(bea_nipa_observations);")
    for row in cursor.fetchall():
        print(f"  {row}")
        
    conn.close()

if __name__ == "__main__":
    verify_table()
