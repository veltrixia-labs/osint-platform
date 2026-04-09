import urllib.request
import json

BASE_URL = "http://localhost:8000"
TEST_CHAT_ID = "stripe_tester"
TEST_PASSWORD = "password123"

def get_token():
    url = f"{BASE_URL}/api/auth/login"
    data = json.dumps({
        "telegram_chat_id": TEST_CHAT_ID,
        "password": TEST_PASSWORD
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]

def verify_checkout():
    try:
        token = get_token()
    except Exception as e:
        print(f"Login failed: {e}")
        return

    print(f"Authenticated as {TEST_CHAT_ID}.")
    
    url = f"{BASE_URL}/api/payments/checkout-session?tier=pro&report_id=6ba7b8109dad11d180b400c04fd430c8"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    
    print("Requesting Stripe Checkout Session...")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            if "url" in data:
                print(f"SUCCESS: Stripe URL generated: {data['url']}")
                # Extract session ID if possible or just print whole data
                print(f"DEBUG: Session Data: {data}")
            else:
                print(f"FAILURE: Unexpected response: {data}")
    except urllib.error.HTTPError as e:
        print(f"FAILURE: HTTP {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"EXCEPTION: {e}")

if __name__ == "__main__":
    verify_checkout()
