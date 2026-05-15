import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_sources.worldbank_client import WorldBankClient
from data_sources.worldbank_indicator_catalog import get_all_indicators

OUTPUT_FILE = Path("scratch/worldbank_sample.json")

async def test_worldbank_api():
    print("="*60)
    print("WORLD BANK API CONNECTIVITY TEST")
    print("="*60)
    
    client = WorldBankClient()
    
    countries = ["US", "JP", "CN", "DE", "GB"]
    indicators = get_all_indicators()
    
    current_year = datetime.now().year
    start_year = current_year - 11 # Approx 10 years of data
    end_year = current_year - 1
    
    print(f"Countries: {countries}")
    print(f"Period: {start_year} - {end_year}")
    
    all_results = {}

    for ind in indicators:
        ind_id = ind["indicator_id"]
        print(f"\nFetching: {ind_id} ({ind['name']})...")
        
        data = client.get_indicator(countries, ind_id, start_year, end_year)
        
        if data:
            # Clean and format for output
            formatted_data = [client.format_data_point(dp) for dp in data if dp.get("value") is not None]
            print(f"  Successfully fetched {len(formatted_data)} valid data points.")
            
            # Print sample (latest year for first country)
            if formatted_data:
                sample = formatted_data[0]
                print(f"  Sample: {sample['country_id']} ({sample['date']}) = {sample['value']}")
            
            all_results[ind_id] = {
                "metadata": ind,
                "data": formatted_data
            }
        else:
            print(f"  No data returned for {ind_id}")

    # Save to JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print(f"Test completed. Results saved to {OUTPUT_FILE}")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_worldbank_api())
