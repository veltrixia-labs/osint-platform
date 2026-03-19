import asyncio
from db.database import engine, Base
from sqlalchemy import text
from db.models import RawItem, Item, Topic, ItemTopic, Report, SignalRanking, ArticleOutput, PdfJob, JobRun, SourceRegistry, SourceHealthLog, ReportTriggerLog, AnalysisCache

async def fix_schema():
    async with engine.begin() as conn:
        # 1. Create all missing tables (like AnalysisCache)
        await conn.run_sync(Base.metadata.create_all)
        
        # 2. Check and add columns to 'items'
        # Get existing columns
        res = await conn.execute(text("PRAGMA table_info(items)"))
        cols = [row[1] for row in res.fetchall()]
        
        if "rough_category" not in cols:
            print("Adding rough_category to items")
            await conn.execute(text("ALTER TABLE items ADD COLUMN rough_category TEXT"))
        
        if "lightweight_score" not in cols:
            print("Adding lightweight_score to items")
            await conn.execute(text("ALTER TABLE items ADD COLUMN lightweight_score FLOAT DEFAULT 0.0"))
            
    print("Schema fix completed.")

if __name__ == "__main__":
    asyncio.run(fix_schema())
