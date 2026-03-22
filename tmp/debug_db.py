import sqlite3

def check_db():
    c = sqlite3.connect('C:/RDTP project/Development/OSINT_analytics/osint_platform.db')
    row = c.execute("SELECT telegram_chat_id, stripe_customer_id, subscription_tier FROM analyst_profiles WHERE telegram_chat_id='testuser'").fetchone()
    print("DB STATE: ", row)
    
if __name__ == "__main__":
    check_db()
