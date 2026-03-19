import asyncio
import os
import sys
sys.path.append(os.getcwd())
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import ExternalPost, Report

async def check_posts():
    async with AsyncSessionLocal() as session:
        # Check ExternalPost entries
        stmt = select(ExternalPost)
        posts = (await session.execute(stmt)).scalars().all()
        print(f"--- ExternalPost Entries ({len(posts)}) ---")
        for p in posts:
            print(f"Platform: {p.platform}, ReportID: {p.report_id}, Status: {p.status}, Error: {p.error_message}")
        
        # Check if the global report was created
        stmt_report = select(Report).where(Report.topic_code == None) # global is None in topic_code usually
        reports = (await session.execute(stmt_report)).scalars().all()
        print(f"\n--- Global Reports ({len(reports)}) ---")
        for r in reports:
            print(f"ID: {r.id}, CreatedAt: {r.created_at}")

if __name__ == "__main__":
    asyncio.run(check_posts())
