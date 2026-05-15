import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from data_sources.bls_client import BLSClient
from data_sources.bls_series_catalog import get_all_bls_series, get_bls_series_ids

OUTPUT_FILE = Path("scratch/bls_sample.json")

async def test_bls_api():
    print("="*60)
    print("BLS API CONNECTIVITY TEST (PPI)")
    print("="*60)
    
    client = BLSClient()
    
    # BLS API v2 requires start and end years
    current_year = datetime.now().year
    start_year = current_year - 1
    end_year = current_year
    
    series_ids = get_bls_series_ids()
    print(f"Fetching data for series: {series_ids}")
    print(f"Period: {start_year} - {end_year}")
    
    # 1. Fetch Data
    response = client.get_timeseries(series_ids, start_year, end_year)
    
    if response.get("status") != "REQUEST_SUCCEEDED":
        print(f"  API Request failed: {response.get('status')}")
        print(f"  Messages: {response.get('message')}")
        # Note: If unauthorized, BLS might still return success but empty data or a specific message.
        
    parsed_data = client.parse_series_data(response)
    
    catalog_series = get_all_bls_series()
    final_output = []

    for series_meta in catalog_series:
        sid = series_meta["series_id"]
        data_points = parsed_data.get(sid, [])
        
        print(f"\nSeries: {sid} ({series_meta['name']})")
        print(f"Category: {series_meta['category']}")
        
        if data_points:
            print(f"  Successfully fetched {len(data_points)} observations.")
            # Print latest 3
            for dp in data_points[:3]:
                print(f"    Date: {dp['year']} {dp['periodName']} | Value: {dp['value']}")
        else:
            print(f"  No data returned for this series.")

        final_output.append({
            "series_id": sid,
            "name": series_meta["name"],
            "category": series_meta["category"],
            "unit": series_meta["unit"],
            "pro_use": series_meta["pro_use"],
            "observations": data_points
        })

    # Save to JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print(f"Test completed. Results saved to {OUTPUT_FILE}")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_bls_api())
