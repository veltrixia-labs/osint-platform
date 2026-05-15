import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import AsyncSessionLocal
from data_sources.bls_ppi_repository import upsert_ppi_observations, count_ppi_rows, get_ppi_series_summary

INPUT_FILE = Path("scratch/bls_ppi_normalized.json")

async def test_ppi_db_save():
    if not INPUT_FILE.exists():
        print(f"Error: Input file {INPUT_FILE} not found. Run normalization script first.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        rows = json.load(f)

    print(f"Read {len(rows)} normalized PPI rows from JSON.\n")

    # ── 1. First Run (Insert/Upsert) ───────────────────────────────
    print("="*60)
    print("RUN 1: Initial Save")
    print("="*60)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result1 = await upsert_ppi_observations(session, rows)
    
    print(f"  Inserted: {result1['inserted']}")
    print(f"  Updated:  {result1['updated']}")
    print(f"  Skipped:  {result1['skipped']}")

    async with AsyncSessionLocal() as session:
        total_count = await count_ppi_rows(session)
        print(f"\n  Total rows in DB: {total_count}")

    # ── 2. Second Run (Idempotency Check) ──────────────────────────
    print("\n" + "="*60)
    print("RUN 2: Idempotency Check")
    print("="*60)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result2 = await upsert_ppi_observations(session, rows)
    
    print(f"  Inserted: {result2['inserted']}")
    print(f"  Updated:  {result2['updated']}")
    print(f"  Skipped:  {result2['skipped']}")

    async with AsyncSessionLocal() as session:
        final_count = await count_ppi_rows(session)
        print(f"\n  Total rows in DB after Run 2: {final_count}")

    # ── 3. Series Summary ──────────────────────────────────────────
    print("\n" + "="*60)
    print("SERIES SUMMARY & LATEST CHECK")
    print("="*60)
    async with AsyncSessionLocal() as session:
        summary = await get_ppi_series_summary(session)
        
        for s in summary:
            status = "OK" if s['latest_count'] == 1 else "ERROR (latest_count != 1)"
            print(f"  {s['series_id']:<12}: {s['total_count']:>3} rows | LatestCount: {s['latest_count']} | {status}")

    if result2['inserted'] == 0 and final_count == total_count:
        print("\n  SUCCESS: Idempotency verified. No new rows inserted on second run.")
    else:
        print("\n  FAILURE: Rows were inserted on second run or count mismatch.")

if __name__ == "__main__":
    asyncio.run(test_ppi_db_save())
