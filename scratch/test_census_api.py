import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from data_sources.census_client import CensusClient

OUTPUT_FILE = Path("scratch/census_sample.json")

async def test_census_api():
    print("="*60)
    print("CENSUS API CONNECTIVITY TEST")
    print("="*60)
    
    client = CensusClient()
    
    test_datasets = [
        {
            "name": "Small Area Income and Poverty Estimates (SAIPE)",
            "path": "timeseries/poverty/saipe",
            "params": {"get": "NAME,SAEPOVRTALL_PT", "for": "state:06", "time": "2022"}
        },
        {
            "name": "County Business Patterns (CBP) 2022",
            "path": "2022/cbp",
            "params": {"get": "NAME,EMP,ESTAB", "for": "state:06"}
        },
        {
            "name": "Economic Indicators (Advance Retail Sales)",
            "path": "indicators/econs/mars",
            "params": {"get": "cell_value,time_slot_id", "for": "us:*", "time": "2023"}
        }
    ]

    all_results = {}

    for ds in test_datasets:
        path = ds["path"]
        name = ds["name"]
        
        print(f"\n--- Testing Dataset: {name} ---")
        print(f"Path: {path}")
        
        # 1. Fetch Variables Metadata
        print("Fetching variables...")
        variables = client.get_variables(path)
        if "error" in variables:
            print(f"  Failed to fetch variables: {variables['error']}")
        else:
            var_count = len(variables.get("variables", {}))
            print(f"  Found {var_count} variables.")

        # 2. Fetch Sample Data
        print(f"Fetching sample data with params: {ds['params']}")
        raw_data = client.get(path, ds["params"])
        
        formatted_data = client.format_as_dicts(raw_data)
        
        if formatted_data:
            print(f"  Successfully fetched {len(formatted_data)} rows.")
            print(f"  Sample row: {formatted_data[0]}")
        else:
            print(f"  No data returned or error: {raw_data}")

        all_results[path] = {
            "name": name,
            "variable_summary": list(variables.get("variables", {}).keys())[:10] if "variables" in variables else [],
            "data_sample": formatted_data[:5]
        }

    # Save to JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print(f"Test completed. Results saved to {OUTPUT_FILE}")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_census_api())
