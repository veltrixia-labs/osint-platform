import urllib.request
import json
import sqlite3

BASE_URL = "http://localhost:8000"
TEST_CHAT_ID = "stripe_tester"
TEST_PASSWORD = "password123"
# The REAL session ID generated and 'paid' in the previous step
SESSION_ID = "cs_test_a1PHaMb8w9kZHtTzNv5OviruZp8S1m1WeOS63YjXlf8WTPy8pzsqOCk34S"

def get_token():
    url = f"{BASE_URL}/api/auth/login"
    data = json.dumps({"telegram_chat_id": TEST_CHAT_ID, "password": TEST_PASSWORD}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]

def verify_fulfillment():
    token = get_token()
    print(f"Authenticated as {TEST_CHAT_ID}.")
    
    # 1. Check BEFORE state
    conn = sqlite3.connect('osint_platform.db')
    cur = conn.cursor()
    cur.execute("SELECT subscription_tier FROM analyst_profiles WHERE telegram_chat_id=?", (TEST_CHAT_ID,))
    before_tier = cur.fetchone()[0]
    print(f"Tier BEFORE fulfillment: {before_tier}")
    
    # 2. Call confirm-session
    url = f"{BASE_URL}/api/payments/confirm-session"
    payload = json.dumps({"session_id": SESSION_ID}).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }, method="POST")
    
    print(f"Calling confirm-session for {SESSION_ID}...")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            print(f"Fulfillment API Response: {data}")
            
        # 3. Check AFTER state
        cur.execute("SELECT subscription_tier FROM analyst_profiles WHERE telegram_chat_id=?", (TEST_CHAT_ID,))
        after_tier = cur.fetchone()[0]
        print(f"Tier AFTER fulfillment: {after_tier}")
        
        # 4. Check Report Unlock
        report_id = "6ba7b8109dad11d180b400c04fd430c8"
        url_report = f"{BASE_URL}/api/reports/{report_id}"
        req_report = urllib.request.Request(url_report, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req_report) as resp:
            report_data = json.loads(resp.read())
            is_locked = report_data.get("locked", True)
            print(f"Report Unlock Status (locked): {is_locked}")
            
        if after_tier == "pro" and is_locked is False:
            print("FINAL STATUS: READY")
        else:
            print("FINAL STATUS: BLOCKED (Logic failure)")
            
    except urllib.error.HTTPError as e:
        print(f"FAILURE: HTTP {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"EXCEPTION: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    verify_fulfillment()
