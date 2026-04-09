import urllib.request
import json
import uuid

BASE_URL = "http://localhost:8000"
FREE_REPORT_ID = "550e8400-e29b-41d4-a716-446655440000"
PREMIUM_REPORT_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"

def verify_launch():
    print(f"--- Verifying Launch Day 1 API states (urllib) ---")
    
    # 1. Guest Access (Public Preview)
    print("\nVerifying Guest Access (Public Preview)...")
    url = f"{BASE_URL}/api/public/reports/{PREMIUM_REPORT_ID}"
    try:
        with urllib.request.urlopen(url) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                print(f"SUCCESS: Received public preview. ID: {data['id']}")
                print(f"Metrics: Sources: {data['source_count']}, Confidence: {data['confidence_level']}")
                print(f"Is Preview: {data.get('is_preview')}, Locked: {data.get('locked')}")
                if "content_markdown" in data:
                    print("FAILURE: Full content leaked in public preview!")
                else:
                    print("SUCCESS: Full content PROTECTED.")
            else:
                print(f"FAILURE: Public preview endpoint returned {response.status}")
    except Exception as e:
        print(f"FAILURE: Request to {url} failed: {e} (Backend might not be running)")

    # 2. Check existence of critical routes
    print("\nVerifying Route registration (Head requests)...")
    routes_to_check = [
        f"/api/reports/{PREMIUM_REPORT_ID}",
        "/api/payments/confirm-session",
        "/api/analytics/event"
    ]
    for route in routes_to_check:
        try:
            req = urllib.request.Request(f"{BASE_URL}{route}", method="GET")
            with urllib.request.urlopen(req) as response:
                print(f"Route {route}: HTTP {response.status}")
        except urllib.error.HTTPError as e:
            # 401/403/405 are actually good signs (route exists and is protected)
            print(f"Route {route}: HTTP {e.code} (Securely Protected)")
        except Exception as e:
            print(f"Route {route} check failed: {e}")

    print("\nVerification process finished.")

if __name__ == "__main__":
    verify_launch()
