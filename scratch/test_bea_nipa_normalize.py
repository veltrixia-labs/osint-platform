import os
import json
import sys
from pathlib import Path
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_sources.bea_nipa_normalizer import normalize_nipa_data

INPUT_DIR = Path("scratch/bea_nipa")
OUTPUT_DIR = Path("scratch/bea_nipa_normalized")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def test_nipa_normalization():
    if not INPUT_DIR.exists():
        print(f"Error: Input directory {INPUT_DIR} not found. Run fetch script first.")
        return

    all_normalized = []
    table_counts = defaultdict(int)
    
    # List all JSON files in input dir
    json_files = sorted([f for f in os.listdir(INPUT_DIR) if f.endswith(".json")])
    
    print(f"Found {len(json_files)} NIPA JSON files to normalize.\n")

    for filename in json_files:
        with open(INPUT_DIR / filename, "r", encoding="utf-8") as f:
            raw_json = json.load(f)
        
        normalized_rows = normalize_nipa_data(raw_json, frequency="A")
        
        if normalized_rows:
            table_name = normalized_rows[0].get("table_name", "Unknown")
            table_counts[table_name] += len(normalized_rows)
            all_normalized.extend(normalized_rows)
            
            # Save individual normalized file
            out_filename = filename.replace(".json", "_normalized.json")
            with open(OUTPUT_DIR / out_filename, "w", encoding="utf-8") as f:
                json.dump(normalized_rows, f, indent=2, ensure_ascii=False)
        
        print(f"Normalized {filename}: {len(normalized_rows)} rows.")

    # Save combined file
    combined_file = OUTPUT_DIR / "all_nipa_normalized.json"
    with open(combined_file, "w", encoding="utf-8") as f:
        json.dump(all_normalized, f, indent=2, ensure_ascii=False)

    # Summary
    print("\n" + "="*50)
    print("NIPA NORMALIZATION SUMMARY")
    print("="*50)
    print(f"Total files processed: {len(json_files)}")
    print(f"Total rows normalized: {len(all_normalized)}")
    print("\nRows per TableName:")
    for table, count in sorted(table_counts.items()):
        print(f"  {table}: {count} rows")
    
    print(f"\nCombined file saved: {combined_file}")

    # Print top 5
    print("\nTop 5 Normalized Rows Sample:")
    for row in all_normalized[:5]:
        print(json.dumps(row, indent=2, ensure_ascii=False))

    # Example of comma removal
    print("\nVerification: Comma removal and float conversion examples")
    for row in all_normalized:
        if row["table_name"] == "T10105" and row["line_number"] == "1":
            print(f"  T10105 Line 1 ({row['time_period']}): {row['data_value']} (Type: {type(row['data_value']).__name__})")
            break
    for row in all_normalized:
        if row["table_name"] == "T10101" and row["line_number"] == "1":
            print(f"  T10101 Line 1 ({row['time_period']}): {row['data_value']} (Type: {type(row['data_value']).__name__})")
            break

if __name__ == "__main__":
    test_nipa_normalization()
