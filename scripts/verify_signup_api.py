import requests
import json
import uuid

API_BASE = "http://localhost:8000/api"

def test_signup():
    test_id = f"test_user_{uuid.uuid4().hex[:6]}"
    signup_data = {
        "telegram_chat_id": test_id,
        "password": "test_password_123"
    }
    
    print(f"Testing signup for {test_id}...")
    
    # 1. Test Successful Signup
    resp = requests.post(f"{API_BASE}/auth/signup", json=signup_data)
    print(f"Response Status: {resp.status_code}")
    print(f"Response Body: {resp.json()}")
    
    if resp.status_code != 201:
        print("FAIL: Expected status code 201")
        return False
        
    # 2. Test Duplicate Signup
    print("\nTesting duplicate signup...")
    resp_dup = requests.post(f"{API_BASE}/auth/signup", json=signup_data)
    print(f"Duplicate Status: {resp_dup.status_code}")
    print(f"Duplicate Body: {resp_dup.json()}")
    
    if resp_dup.status_code != 400:
        print("FAIL: Expected status code 400 for duplicate")
        return False
        
    # 3. Verify Login with New User
    print("\nTesting login with new user...")
    login_resp = requests.post(f"{API_BASE}/auth/login", json=signup_data)
    print(f"Login Status: {login_resp.status_code}")
    
    if login_resp.status_code != 200:
        print("FAIL: Login should work for newly created user")
        return False
        
    print("\nBACKEND SIGNUP VERIFICATION SUCCESSFUL")
    return True

if __name__ == "__main__":
    try:
        test_signup()
    except Exception as e:
        print(f"ERROR: {e}")
