import os
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_sources.bls_client import BLSClient

# Series IDs from user request
SERIES_IDS = [
    "WPUFD4",        # PPI Final demand
    "WPUFD49104",    # Final demand goods
    "WPUFD49207",    # Final demand services
    "WPU057",        # Fuels and related products and power
    "WPU101",        # Iron and steel
    "WPU081",        # Lumber and wood products
    "WPU114",        # Machinery and equipment
    "WPU117",        # Electronic components and accessories
]

SAMPLE_OUTPUT = Path("scratch/bls_ppi_sample.json")

def test_bls_ppi():
    print("="*60)
    print("BLS PPI API CONNECTION TEST (2018-2024)")
    print("="*60)

    client = BLSClient()
    response = client.get_timeseries(SERIES_IDS, 2018, 2024)

    status = response.get("status")
    message = response.get("message", [])
    
    print(f"API Status: {status}")
    if message:
        print(f"API Messages: {message}")

    if status != "REQUEST_SUCCEEDED":
        print("\nRequest did not succeed. Check series IDs or rate limits.")
        # If we got a response but with warnings/errors
        if "Results" not in response:
            return

    # Save raw response for analysis
    with open(SAMPLE_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(response, f, indent=2, ensure_ascii=False)
    print(f"\nRaw response saved to {SAMPLE_OUTPUT}")

    # Summarize results
    series_results = response.get("Results", {}).get("series", [])
    success_ids = []
    fail_ids = []

    print("\nSeries Summary:")
    for s in series_results:
        sid = s.get("seriesID")
        data = s.get("data", [])
        
        if data:
            success_ids.append(sid)
            latest = data[0] # Usually sorted descending by time
            print(f"  [SUCCESS] {sid:<12}: {len(data):>3} points. Latest: {latest.get('year')}-{latest.get('periodName')} = {latest.get('value')}")
        else:
            fail_ids.append(sid)
            print(f"  [EMPTY  ] {sid:<12}: No data returned.")

    # Check for IDs that aren't even in the results
    returned_ids = [s.get("seriesID") for s in series_results]
    for sid in SERIES_IDS:
        if sid not in returned_ids:
            fail_ids.append(sid)
            print(f"  [MISSING] {sid:<12}: Not found in response Results.")

    print("\n" + "="*60)
    print(f"SUMMARY: {len(success_ids)} Successful, {len(fail_ids)} Failed/Empty")
    print("="*60)

if __name__ == "__main__":
    test_bls_ppi()
