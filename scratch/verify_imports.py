import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

routes_to_test = [
    "api.routes.alerts",
    "api.routes.reports",
    "api.routes.analysts",
    "api.routes.system",
    "api.routes.insights",
    "api.routes.analytics",
    "api.main"
]

all_success = True
for r in routes_to_test:
    try:
        print(f"Testing {r} imports...")
        __import__(r)
        print(f"SUCCESS: {r}")
    except Exception as e:
        print(f"FAILED: {r} - {e}")
        all_success = False

if all_success:
    print("\nOVERALL VERIFICATION: PASSED")
else:
    print("\nOVERALL VERIFICATION: FAILED")
    sys.exit(1)
