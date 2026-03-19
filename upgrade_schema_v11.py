import asyncio
from db.database import engine, Base
from sqlalchemy import text
from db.models import EventCluster, Item

async def upgrade_schema():
    async with engine.begin() as conn:
        # 1. Create EventCluster table
        await conn.run_sync(Base.metadata.create_all)
        
        # 2. Add cluster_id to items
        res = await conn.execute(text("PRAGMA table_info(items)"))
        cols = [row[1] for row in res.fetchall()]
        
        if "cluster_id" not in cols:
            print("Adding cluster_id to items")
            # SQLite doesn't support complex FK additions via ALTER TABLE easily, 
            # but we can add the column.
            await conn.execute(text("ALTER TABLE items ADD COLUMN cluster_id CHAR(32)"))
            
    print("Schema upgrade to Phase 11 completed.")

if __name__ == "__main__":
    asyncio.run(upgrade_schema())
