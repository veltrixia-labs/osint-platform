import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from sqlalchemy import text
from db.database import engine

async def verify_schema():
    async with engine.connect() as conn:
        # Check table info
        print("Checking table_info for bls_ppi_observations:")
        result = await conn.execute(text("PRAGMA table_info(bls_ppi_observations)"))
        for row in result:
            print(f"  {row}")
        
        # Check indexes
        print("\nChecking indexes for bls_ppi_observations:")
        result = await conn.execute(text("PRAGMA index_list(bls_ppi_observations)"))
        for row in result:
            print(f"  {row}")

        # Check existing table to ensure no impact
        print("\nVerifying existing table 'bea_nipa_observations' still exists:")
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='bea_nipa_observations'"))
        exists = result.scalar()
        print(f"  Exists: {exists}")

if __name__ == "__main__":
    asyncio.run(verify_schema())
