"""
Test script for BEA normalizer.

Reads the raw JSON saved by test_bea_api.py, normalizes it,
prints the first 5 rows and total count, then saves the result.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path to import data_sources
sys.path.append(str(Path(__file__).parent.parent))

from data_sources.bea_normalizer import normalize_gdp_by_industry


def main():
    scratch_dir = Path(__file__).parent
    input_file = scratch_dir / "bea_gdpbyindustry_table1_2022_a.json"

    # ── 1. Load raw JSON ──────────────────────────────────────────────
    if not input_file.exists():
        print(f"Error: input file not found: {input_file}")
        print("Run test_bea_api.py first to generate the raw JSON.")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        raw_json = json.load(f)

    # ── 2. Normalize ──────────────────────────────────────────────────
    rows = normalize_gdp_by_industry(raw_json)

    # ── 3. Print first 5 rows ─────────────────────────────────────────
    print("=" * 70)
    print("First 5 normalized rows:")
    print("=" * 70)
    for i, row in enumerate(rows[:5]):
        print(json.dumps(row, indent=2, ensure_ascii=False))
        if i < 4:
            print("-" * 40)

    # ── 4. Print total count ──────────────────────────────────────────
    print("=" * 70)
    print(f"Total normalized rows: {len(rows)}")
    print("=" * 70)

    # ── 5. Save normalized JSON ───────────────────────────────────────
    output_file = scratch_dir / "bea_gdpbyindustry_table1_2022_a_normalized.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"\nSaved normalized JSON to: {output_file}")


if __name__ == "__main__":
    main()
