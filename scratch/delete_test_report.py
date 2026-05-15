import asyncio
import sys
import os
from sqlalchemy import delete

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import Report

import uuid

async def delete_test_report():
    report_id = "bc63d707-cbfa-4968-b8da-3466823c1943"
    async with AsyncSessionLocal() as db:
        print(f"Deleting report {report_id}...")
        await db.execute(delete(Report).where(Report.id == uuid.UUID(report_id)))
        await db.commit()
        print("Deleted.")

if __name__ == "__main__":
    asyncio.run(delete_test_report())
