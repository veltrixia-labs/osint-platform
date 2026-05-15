"""
Verifies that MarketData models and tables are correctly registered in the database.
"""

import asyncio
import sys
import os
import logging
from sqlalchemy import select, func, inspect

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import engine, AsyncSessionLocal
from db.models import (
    MarketDataInstrument,
    MarketDataPrice,
    MarketDataFetchLog
)

async def check_schema():
    async with engine.connect() as conn:
        # Use sync inspect on the underlying connection
        def get_tables(connection):
            return inspect(connection).get_table_names()
        
        tables = await conn.run_sync(get_tables)
        
        target_tables = ["market_data_instruments", "market_data_prices", "market_data_fetch_logs"]
        print("Checking tables in database:")
        for table in target_tables:
            if table in tables:
                print(f"  [OK] Table '{table}' exists.")
            else:
                print(f"  [FAIL] Table '{table}' NOT found.")

async def check_models():
    async with AsyncSessionLocal() as db:
        print("\nChecking model queries:")
        try:
            # Check Instrument
            inst_count = (await db.execute(select(func.count()).select_from(MarketDataInstrument))).scalar()
            print(f"  [OK] MarketDataInstrument query successful (Count: {inst_count})")
            
            # Check Price
            price_count = (await db.execute(select(func.count()).select_from(MarketDataPrice))).scalar()
            print(f"  [OK] MarketDataPrice query successful (Count: {price_count})")
            
            # Check FetchLog
            log_count = (await db.execute(select(func.count()).select_from(MarketDataFetchLog))).scalar()
            print(f"  [OK] MarketDataFetchLog query successful (Count: {log_count})")
            
        except Exception as e:
            print(f"  [FAIL] Model query failed: {e}")

async def run_check():
    print("=" * 60)
    print("MARKET DATA DB MODELS CHECK")
    print("=" * 60)
    
    await check_schema()
    await check_models()
    
    print("\n" + "=" * 60)
    print("Check completed.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_check())
