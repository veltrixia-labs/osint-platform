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

TARGET_DATASETS = [
    "NIPA",
    "GDPbyIndustry",
    "InputOutput",
    "Regional",
    "International",
    "ITA",
    "UnderlyingGDPbyIndustry"
]

INTERESTING_PARAMS = [
    "TableName",
    "TableID",
    "LineCode",
    "Industry",
    "GeoFips",
    "Frequency",
    "Year"
]

METADATA_DIR = Path("scratch/bea_dataset_metadata")
METADATA_DIR.mkdir(parents=True, exist_ok=True)

def save_json(data: Any, filename: str):
    path = METADATA_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved: {path}")

def explore():
    try:
        client = BEAClient()
    except ValueError as e:
        print(f"Error: {e}")
        return

    print("Fetching dataset list...")
    datasets_resp = client.get_datasets()
    save_json(datasets_resp, "all_datasets.json")
    
    available_datasets = []
    try:
        ds_list = datasets_resp.get("BEAAPI", {}).get("Results", {}).get("Dataset", [])
        available_datasets = [ds.get("DatasetName") for ds in ds_list]
    except Exception as e:
        print(f"Could not parse dataset list: {e}")

    for ds_name in TARGET_DATASETS:
        print(f"\n Exploring Dataset: {ds_name}")
        if ds_name not in available_datasets:
            print(f"  Warning: {ds_name} not found in available datasets list.")
            # We still try to fetch parameter list in case the list was incomplete or different
            
        try:
            # 1. Get Parameter List
            print(f"  Fetching ParameterList for {ds_name}...")
            param_list_resp = client.get_parameter_list(ds_name)
            save_json(param_list_resp, f"{ds_name}_parameters.json")
            
            # 2. Extract parameters and fetch values for interesting ones
            params = []
            try:
                results = param_list_resp.get("BEAAPI", {}).get("Results", [])
                if isinstance(results, list) and len(results) > 0:
                    params = results[0].get("Parameter", [])
                elif isinstance(results, dict):
                    params = results.get("Parameter", [])
            except Exception as e:
                print(f"  Could not parse parameter list for {ds_name}: {e}")
                continue

            param_names = [p.get("ParameterName") for p in params]
            print(f"  Parameters: {', '.join(param_names)}")
            
            # 3. Get Parameter Values for interesting parameters
            param_values_combined = {}
            for p_name in param_names:
                if p_name in INTERESTING_PARAMS:
                    print(f"    Fetching ParameterValues for {p_name}...")
                    try:
                        val_resp = client.get_parameter_values(ds_name, p_name)
                        # We only save the actual values to keep it concise in the combined file
                        try:
                            val_results = val_resp.get("BEAAPI", {}).get("Results", [])
                            if isinstance(val_results, list) and len(val_results) > 0:
                                values = val_results[0].get("ParamValue", [])
                            elif isinstance(val_results, dict):
                                values = val_results.get("ParamValue", [])
                            else:
                                values = val_results
                            
                            param_values_combined[p_name] = values
                        except:
                            param_values_combined[p_name] = val_resp
                    except Exception as e:
                        print(f"    Error fetching values for {p_name}: {e}")
                    
                    time.sleep(0.5) # Polite delay

            if param_values_combined:
                save_json(param_values_combined, f"{ds_name}_parameter_values.json")

        except Exception as e:
            print(f"  Error exploring {ds_name}: {e}")
        
        time.sleep(1) # Polite delay between datasets

if __name__ == "__main__":
    explore()
