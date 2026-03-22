import httpx
import urllib.parse
import sqlite3

def test_api():
    # 1. get token
    r = httpx.post("http://localhost:8000/api/auth/login", json={"telegram_chat_id": "testuser", "password": "password123"})
    token = r.json().get("access_token")
    
    # 2. encode returnUrl like JS does
    returnUrl = urllib.parse.quote("http://localhost:5173", safe="")
    
    url = f"http://localhost:8000/api/payments/checkout-session?tier=pro&return_url={returnUrl}&report_id=test_rep"
    print("Fetching:", url)
    
    headers = {"Authorization": f"Bearer {token}"}
    r2 = httpx.get(url, headers=headers)
    print("Status:", r2.status_code)
    print("Response STR:", r2.text)

if __name__ == "__main__":
    test_api()
