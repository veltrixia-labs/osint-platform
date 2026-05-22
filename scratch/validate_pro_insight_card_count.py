"""Verify at most one pro_structural brief per domain topic_code."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv

load_dotenv()

from collections import Counter
from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import Report
from jobs.pro_structural_reports import pro_structural_report_filters


async def main() -> None:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Report).where(*pro_structural_report_filters()))).scalars().all()
    counts = Counter((r.topic_code or "global") for r in rows)
    dupes = {k: v for k, v in counts.items() if v > 1}
    print(f"total_rows={len(rows)} domains={len(counts)} duplicates={dupes or 'none'}")
    if dupes:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
