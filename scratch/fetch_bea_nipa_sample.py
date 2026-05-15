import os
import json
import time
import sys
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_sources.bea_client import BEAClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TABLE_NAMES = ["T10101", "T10105", "T20305"]
YEARS = ["2018", "2019", "2020", "2021", "2022", "2023", "2024"]
DATASET = "NIPA"
FREQUENCY = "A"

OUTPUT_DIR = Path("scratch/bea_nipa")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def fetch_nipa_samples():
    try:
        client = BEAClient()
    except ValueError as e:
        print(f"Error initializing BEAClient: {e}")
        return

    errors = []
    fetch_summary = {table: 0 for table in TABLE_NAMES}
    first_samples = {}

    print(f"Starting NIPA data fetch for tables: {', '.join(TABLE_NAMES)}")
    print(f"Target years: {', '.join(YEARS)}\n")

    for table in TABLE_NAMES:
        for year in YEARS:
            print(f"Fetching {table} for {year}...")
            try:
                # API Call
                resp = client.get_data(
                    dataset_name=DATASET,
                    TableName=table,
                    Frequency=FREQUENCY,
                    Year=year
                )
                
                # Check for API-level errors in response
                results = resp.get("BEAAPI", {}).get("Results", {})
                if isinstance(results, dict) and "Error" in results:
                    err_msg = results.get("Error", {}).get("ErrorDetail", "Unknown API Error")
                    print(f"  API Error for {table} {year}: {err_msg}")
                    errors.append(f"{table} {year}: {err_msg}")
                    continue

                # Extract data
                data = []
                if isinstance(results, list) and len(results) > 0:
                    data = results[0].get("Data", [])
                elif isinstance(results, dict):
                    data = results.get("Data", [])

                row_count = len(data)
                print(f"  Success: {row_count} rows retrieved.")
                
                if row_count > 0:
                    sample = data[0]
                    print(f"  Sample: {json.dumps(sample, ensure_ascii=False)}")
                    if table not in first_samples:
                        first_samples[table] = sample
                    
                    # Save raw JSON
                    filename = f"nipa_{table}_{year}_a.json"
                    with open(OUTPUT_DIR / filename, "w", encoding="utf-8") as f:
                        json.dump(resp, f, indent=2, ensure_ascii=False)
                    
                    fetch_summary[table] += row_count
                else:
                    print(f"  Warning: No data found for {table} {year}.")

            except Exception as e:
                print(f"  Exception fetching {table} {year}: {str(e)}")
                errors.append(f"{table} {year}: {str(e)}")

            # Polite delay between requests
            time.sleep(0.5)

    # Summary Output
    print("\n" + "="*50)
    print("NIPA FETCH SUMMARY")
    print("="*50)
    for table, count in fetch_summary.items():
        print(f"Table {table}: {count} total rows across all years")
    
    print("\nSaved JSON Files:")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        if f.endswith(".json"):
            print(f"  {f}")

    if errors:
        print("\nErrors encountered:")
        for err in errors:
            print(f"  - {err}")
    else:
        print("\nNo errors encountered.")

    print("\nFirst Samples per Table:")
    for table, sample in first_samples.items():
        print(f"Table {table}: {json.dumps(sample, indent=2, ensure_ascii=False)}")

if __name__ == "__main__":
    fetch_nipa_samples()
