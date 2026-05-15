import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from data_sources.fred_client import FREDClient
from data_sources.fred_series_catalog import get_all_fred_series, get_fred_series_ids

OUTPUT_FILE = Path("scratch/fred_catalog_sample.json")

async def test_fred_api_with_catalog():
    print("="*60)
    print("FRED API CONNECTIVITY TEST (USING CATALOG)")
    print("="*60)
    
    try:
        client = FREDClient()
    except ValueError as e:
        print(f"Configuration Error: {e}")
        return

    # Get all series metadata from catalog
    catalog_series = get_all_fred_series()
    final_output = []

    for series_meta in catalog_series:
        series_id = series_meta["series_id"]
        category = series_meta["category"]
        name = series_meta["name"]
        
        print(f"\nFetching observations for: {series_id} ({category})...")
        
        # Fetch last 12 observations
        result = client.get_series_observations(series_id, limit=12, sort_order='desc')
        
        if "error" in result or "error_message" in result:
            print(f"  Error fetching {series_id}: {result.get('error_message', result.get('error'))}")
            continue
            
        observations = result.get("observations", [])
        print(f"  Successfully fetched {len(observations)} observations.")
        
        # Print top 3 for visual confirmation
        for obs in observations[:3]:
            print(f"    Date: {obs['date']} | Value: {obs['value']}")
        
        # Combine meta and observations
        final_output.append({
            "series_id": series_id,
            "name": name,
            "category": category,
            "unit": series_meta["unit"],
            "pro_use": series_meta["pro_use"],
            "observations": observations
        })

    # Save to JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print(f"Test completed. Catalog-based results saved to {OUTPUT_FILE}")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_fred_api_with_catalog())
