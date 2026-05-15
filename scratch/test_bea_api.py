import os
import json
from pathlib import Path
import sys

try:
    from dotenv import load_dotenv
    # Load .env from the root of the project
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

# Add parent directory to path to import data_sources
sys.path.append(str(Path(__file__).parent.parent))

from data_sources.bea_client import BEAClient

def main():
    try:
        client = BEAClient()
    except ValueError as e:
        print(f"Error: {e}")
        return

    scratch_dir = Path(__file__).parent
    scratch_dir.mkdir(exist_ok=True)

    print("Fetching dataset list...")
    datasets = client.get_datasets()
    datasets_file = scratch_dir / "bea_datasets.json"
    with open(datasets_file, "w", encoding="utf-8") as f:
        json.dump(datasets, f, indent=2)
    print(f"Saved dataset list to {datasets_file}")

    print("\nFetching GDPbyIndustry parameter list...")
    params_list = client.get_parameter_list("GDPbyIndustry")
    # You could also save the parameter list if you wanted, but it's not strictly required by the prompt
    
    print("\nFetching GDPbyIndustry data...")
    gdp_data = client.get_data(
        dataset_name="GDPbyIndustry",
        TableID="1",
        Industry="ALL",
        Year="2022",
        Frequency="A"
    )
    
    gdp_file = scratch_dir / "bea_gdpbyindustry_table1_2022_a.json"
    with open(gdp_file, "w", encoding="utf-8") as f:
        json.dump(gdp_data, f, indent=2)
    print(f"Saved GDPbyIndustry data to {gdp_file}")
    
    # Verify the IndustryDescription workaround
    try:
        results = gdp_data.get("BEAAPI", {}).get("Results", [])
        if isinstance(results, list) and len(results) > 0:
            data_points = results[0].get("Data", [])
        elif isinstance(results, dict):
            data_points = results.get("Data", [])
        else:
            data_points = []
            
        if data_points:
            sample = data_points[0]
            print("\nSample data point keys:")
            print(list(sample.keys()))
            if "IndustryDescription" in sample:
                print("Successfully found 'IndustryDescription' (workaround applied)")
            elif "IndustrYDescription" in sample:
                print("Found 'IndustrYDescription' but workaround failed to map to 'IndustryDescription'")
    except Exception as e:
        print(f"Could not verify data structure: {e}")

if __name__ == "__main__":
    main()
