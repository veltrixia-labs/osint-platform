import subprocess
import time
import os

# Kill any existing server on 8000
subprocess.run('Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process -Force', shell=True, executable="powershell")

# Start server and capture output to log
log_file = "C:/RDTP project/Development/OSINT_analytics/tmp/backend_debug.log"
with open(log_file, "w") as f:
    process = subprocess.Popen([".venv/Scripts/python.exe", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"], 
                               stdout=f, stderr=f, cwd="C:/RDTP project/Development/OSINT_analytics")

print("Waiting for server to start...")
time.sleep(5)

# Trigger the error
import urllib.request
url = "http://localhost:8000/api/public/reports/6ba7b810-9dad-11d1-80b4-00c04fd430c8"
try:
    urllib.request.urlopen(url)
except Exception as e:
    print(f"Triggered error: {e}")

time.sleep(2)
process.terminate()

# Read the log
if os.path.exists(log_file):
    with open(log_file, "r") as f:
        print("\n--- BACKEND LOG TRACEBACK ---")
        print(f.read())
else:
    print("Log file not found.")
