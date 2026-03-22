import httpx
import sqlite3

def test_api():
    print("--- 1. Authenticating as testuser ---")
    data = {
        "username": "testuser",
        "password": "password123"
    }
    r = httpx.post("http://localhost:8000/api/auth/token", data=data)
    token = r.json().get("access_token")
    print(f"Token obtained: bool({bool(token)})")

    print("\n--- 2. Requesting Checkout Session ---")
    headers = {"Authorization": f"Bearer {token}"}
    r2 = httpx.get("http://localhost:8000/api/payments/checkout-session?tier=pro", headers=headers)
    
    print(f"Status Code: {r2.status_code}")
    print(f"Response: {r2.json()}")
    
    if r2.status_code == 200 and "url" in r2.json():
        print("=> SUCCESS: Real Stripe checkout URL generated.")
    else:
        print("=> FAILURE: Failed to generate checkout URL.")

    print("\n--- 3. Verifying DB State AFTER API Call ---")
    c = sqlite3.connect('C:/RDTP project/Development/OSINT_analytics/osint_platform.db')
    row = c.execute("SELECT telegram_chat_id, stripe_customer_id, subscription_tier FROM analyst_profiles WHERE telegram_chat_id='testuser'").fetchone()
    print("DB STATE (AFTER):", row)

if __name__ == "__main__":
    test_api()
