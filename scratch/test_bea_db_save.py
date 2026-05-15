"""
Test script: load normalized JSON and upsert into bea_gdp_by_industry.

Usage:
    .venv\\Scripts\\python.exe scratch/test_bea_db_save.py
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import AsyncSessionLocal
from data_sources.bea_repository import upsert_gdp_rows, count_gdp_rows


async def main():
    scratch_dir = Path(__file__).parent
    input_file = scratch_dir / "bea_gdpbyindustry_table1_2022_a_normalized.json"

    # ── 1. Load normalized JSON ───────────────────────────────────────
    if not input_file.exists():
        print(f"Error: {input_file} not found. Run test_bea_normalize.py first.")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        rows = json.load(f)

    print(f"Loaded {len(rows)} normalized rows from JSON.")

    # ── 2. Upsert into DB ────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = upsert_gdp_rows(session, rows)
            # upsert_gdp_rows is async
            result = await result if asyncio.iscoroutine(result) else result

        print(f"\nUpsert result:")
        print(f"  Inserted: {result['inserted']}")
        print(f"  Updated:  {result['updated']}")
        print(f"  Skipped:  {result['skipped']}")

    # ── 3. Verify count ──────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        total = await count_gdp_rows(session)
        print(f"\nTotal rows in bea_gdp_by_industry: {total}")


if __name__ == "__main__":
    asyncio.run(main())
