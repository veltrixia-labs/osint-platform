import sqlite3
import os

DB_PATH = 'C:/RDTP project/Development/OSINT_analytics/osint_platform.db'
if os.path.exists(DB_PATH):
    c = sqlite3.connect(DB_PATH)
    c.execute("UPDATE analyst_profiles SET subscription_tier='free', stripe_customer_id=NULL, stripe_subscription_id=NULL, subscription_expires_at=NULL WHERE telegram_chat_id='testuser'")
    c.commit()
    print("testuser reset successful.")
