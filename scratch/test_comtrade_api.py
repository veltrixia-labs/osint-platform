import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from data_sources.comtrade_client import ComtradeClient

OUTPUT_FILE = Path("scratch/comtrade_sample.json")

async def test_comtrade_api():
    print("="*60)
    print("UN COMTRADE API CONNECTIVITY TEST")
    print("="*60)
    
    client = ComtradeClient()
    
    # Test Query: Japan Imports of Semiconductors from World (2023)
    query_params = {
        "reporter_code": "392",     # Japan
        "partner_code": "0",       # World
        "flow_code": "M",          # Imports
        "commodity_code": "8542",  # Electronic integrated circuits
        "year": 2023,
        "frequency": "A"
    }

    print(f"Executing query: {query_params}")
    result = client.get_trade_data(**query_params)
    
    if result.get("error"):
        print(f"\nAPI Error Detected!")
        print(f"Status Code: {result.get('status_code')}")
        print(f"Response: {result.get('response_text')}")
        
        # If 2023 is not available, try 2022
        print("\nRetrying with 2022...")
        query_params["year"] = 2022
        result = client.get_trade_data(**query_params)

    if result.get("error"):
        print(f"Retry failed: {result.get('response_text')}")
        return

    # Process and print results
    data = result.get("data", [])
    print(f"\nSuccessfully fetched {len(data)} records.")
    
    formatted_results = []
    for record in data:
        formatted = {
            "reporter": record.get("reporterDesc"),
            "reporter_code": record.get("reporterCode"),
            "partner": record.get("partnerDesc"),
            "partner_code": record.get("partnerCode"),
            "flow": record.get("flowDesc"),
            "commodity_code": record.get("cmdCode"),
            "commodity_name": record.get("cmdDesc"),
            "year": record.get("period"),
            "trade_value": record.get("primaryValue"),
            "quantity": record.get("qty"),
            "unit": record.get("qtyUnitAbbr"),
            "api_query": result.get("api_query")
        }
        formatted_results.append(formatted)
        
        # Print summary for the first record
        print("\n--- Trade Record Summary ---")
        for key, val in formatted.items():
            if key != "api_query":
                print(f"  {key:<15}: {val}")

    # Save to JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print(f"Test completed. Results saved to {OUTPUT_FILE}")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_comtrade_api())
