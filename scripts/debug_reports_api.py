import urllib.request
import json

url = "http://localhost:8000/api/reports"
try:
    with urllib.request.urlopen(url) as resp:
        print(f"Status: {resp.status}")
        print(json.loads(resp.read()))
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        print(e.read().decode())
