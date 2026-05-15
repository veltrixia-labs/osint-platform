import asyncio
import json
import sys
from pathlib import Path
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import AsyncSessionLocal
from db.models import BEANIPAObservation
from data_sources.bea_nipa_repository import upsert_nipa_observations, count_nipa_rows
from sqlalchemy import select

INPUT_FILE = Path("scratch/bea_nipa_normalized/all_nipa_normalized.json")

async def test_nipa_db_save():
    if not INPUT_FILE.exists():
        print(f"Error: Input file {INPUT_FILE} not found. Run normalization script first.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        rows = json.load(f)

    print(f"Read {len(rows)} normalized NIPA rows from JSON.\n")

    # ── 1. First Run (Insert/Upsert) ───────────────────────────────
    print("="*50)
    print("RUN 1: Initial Save")
    print("="*50)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result1 = await upsert_nipa_observations(session, rows)
    
    print(f"  Inserted: {result1['inserted']}")
    print(f"  Updated:  {result1['updated']}")
    print(f"  Skipped:  {result1['skipped']}")

    async with AsyncSessionLocal() as session:
        total_count = await count_nipa_rows(session)
        print(f"\n  Total rows in DB: {total_count}")

    # ── 2. Second Run (Idempotency Check) ──────────────────────────
    print("\n" + "="*50)
    print("RUN 2: Idempotency Check")
    print("="*50)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result2 = await upsert_nipa_observations(session, rows)
    
    print(f"  Inserted: {result2['inserted']}")
    print(f"  Updated:  {result2['updated']}")
    print(f"  Skipped:  {result2['skipped']}")

    async with AsyncSessionLocal() as session:
        final_count = await count_nipa_rows(session)
        print(f"\n  Total rows in DB after Run 2: {final_count}")

    if result2['inserted'] == 0 and final_count == total_count:
        print("\n  SUCCESS: Idempotency verified. No new rows inserted on second run.")
    else:
        print("\n  FAILURE: Rows were inserted on second run or count mismatch.")

    # ── 3. Table Summary ──────────────────────────────────────────
    print("\n" + "="*50)
    print("TABLE SUMMARY")
    print("="*50)
    async with AsyncSessionLocal() as session:
        stmt = select(BEANIPAObservation.table_name, BEANIPAObservation.time_period)
        result = await session.execute(stmt)
        data = result.all()
        
        counts = defaultdict(int)
        for table, period in data:
            counts[table] += 1
            
        for table, count in sorted(counts.items()):
            print(f"  {table}: {count} rows")

if __name__ == "__main__":
    asyncio.run(test_nipa_db_save())
