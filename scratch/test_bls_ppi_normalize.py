import json
import sys
from pathlib import Path
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_sources.bls_ppi_normalizer import normalize_bls_ppi_data

INPUT_FILE = Path("scratch/bls_ppi_sample.json")
OUTPUT_FILE = Path("scratch/bls_ppi_normalized.json")

def test_bls_ppi_normalize():
    if not INPUT_FILE.exists():
        print(f"Error: Input file {INPUT_FILE} not found. Run fetch script first.")
        return

    print("="*60)
    print("BLS PPI NORMALIZATION TEST")
    print("="*60)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_json = json.load(f)

    normalized_rows = normalize_bls_ppi_data(raw_json)

    # Save results
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized_rows, f, indent=2, ensure_ascii=False)
    print(f"Normalized data saved to {OUTPUT_FILE}")

    # Summary
    print(f"\nTotal normalized rows: {len(normalized_rows)}")
    
    series_counts = defaultdict(int)
    latest_values = {}
    
    for row in normalized_rows:
        sid = row["series_id"]
        series_counts[sid] += 1
        if row["latest"]:
            latest_values[sid] = f"{row['date']}: {row['value']}"

    print("\nRows per Series ID:")
    for sid, count in sorted(series_counts.items()):
        print(f"  {sid:<12}: {count:>3} rows. Latest -> {latest_values.get(sid)}")

    print("\n" + "="*60)
    print("SAMPLE (TOP 5 ROWS)")
    print("="*60)
    for row in normalized_rows[:5]:
        print(json.dumps(row, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_bls_ppi_normalize()
