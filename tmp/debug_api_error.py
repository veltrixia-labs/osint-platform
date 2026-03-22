import requests
import json

url = "https://osint-platform-xs7p.onrender.com/api/reports"
try:
    response = requests.get(url)
    print(f"Status: {response.status_code}")
    print(f"Body: {response.text}")
except Exception as e:
    print(f"Request failed: {e}")
