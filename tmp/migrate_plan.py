
import asyncio
import os
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Add parent dir to path for imports
sys.path.append(os.getcwd())

async def migrate():
    # Detect DB URL from ENV or fallback to local SQLite
    # Since we are in the Workspace, we check the common db path
    db_url = "sqlite+aiosqlite:///osint_platform.db"
    
    print(f"Connecting to {db_url}...")
    engine = create_async_engine(db_url)
    
    async with engine.begin() as conn:
        print("Checking for 'plan_required' column in 'reports' table...")
        try:
            # Check if column exists (SQLite specific check)
            result = await conn.execute(text("PRAGMA table_info(reports)"))
            columns = [row[1] for row in result.fetchall()]
            
            if "plan_required" not in columns:
                print("Adding 'plan_required' column to 'reports' table...")
                await conn.execute(text("ALTER TABLE reports ADD COLUMN plan_required VARCHAR DEFAULT 'free'"))
                print("Migration successful.")
            else:
                print("Column 'plan_required' already exists. Skipping.")
                
        except Exception as e:
            print(f"Migration error: {e}")
            
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(migrate())
