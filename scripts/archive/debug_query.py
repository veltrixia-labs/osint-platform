import asyncio
import uuid
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from db.models import Report

# Hyphen-less hex IDs
FREE_REPORT_ID = "550e8400e29b41d4a716446655440000"
PREMIUM_REPORT_ID = "6ba7b8109dad11d180b400c04fd430c8"

DATABASE_URL = "sqlite+aiosqlite:///c:/RDTP project/Development/OSINT_analytics/osint_platform.db"

async def test_query():
    print("Connecting to DB...")
    engine = create_async_engine(DATABASE_URL)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with AsyncSessionLocal() as db:
        # FastAPI/SQLAlchemy will try to match the uuid.UUID object to the hex string in DB
        rid = uuid.UUID(PREMIUM_REPORT_ID)
        print(f"Querying for ID: {rid}")
        
        try:
            stmt = select(Report).where(Report.id == rid)
            result = await db.execute(stmt)
            report = result.scalar_one_or_none()
            
            if report:
                print(f"SUCCESS: Report found!")
                print(f"Title snippet: {report.content_markdown[:50]}")
                print(f"Premium: {report.is_premium} (Type: {type(report.is_premium)})")
                
                # Test the serialization logic from main.py
                content = report.content_markdown or ""
                paragraphs = [p for p in content.split('\n\n') if p.strip()]
                preview_parts = paragraphs[:3]
                preview_text = "\n\n".join(preview_parts)
                print(f"Preview Logic OK. Length: {len(preview_text)}")
                
                created_at_iso = report.created_at.isoformat() if hasattr(report.created_at, 'isoformat') else report.created_at
                print(f"Created AT Serialization OK: {created_at_iso}")
                
            else:
                print("FAILURE: Report not found in DB.")
        except Exception as e:
            print(f"EXCEPTION: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_query())
