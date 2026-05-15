import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import ExternalTradeFlow
from sqlalchemy import select, func

async def inspect():
    async with AsyncSessionLocal() as db:
        # Count total
        total = (await db.execute(select(func.count()).select_from(ExternalTradeFlow))).scalar()
        print(f"Total records in ExternalTradeFlow: {total}")
        
        # Sample records
        stmt = select(ExternalTradeFlow).limit(20)
        results = (await db.execute(stmt)).scalars().all()
        
        print("\nSample records (first 20):")
        for r in results:
            print(f"  {r.reporter_id} ({r.reporter_name}) -> {r.partner_id} ({r.partner_name}) | {r.flow_type} | {r.commodity_id} | {r.year} | {r.trade_value}")
        
        if results:
            import json
            print("\nSearching for a record with raw_json...")
            sample_with_json = None
            for r in results:
                if r.raw_json:
                    sample_with_json = r
                    break
            
            if sample_with_json:
                print(f"Raw JSON of record {sample_with_json.id}:")
                print(json.dumps(sample_with_json.raw_json, indent=2))
            else:
                print("No record with raw_json found in sample.")

if __name__ == "__main__":
    asyncio.run(inspect())
