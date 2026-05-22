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
    feed_prefixes = ("Rocket Report:", "Breaking:", "Live:", "Structural Impact Brief -")
    for r in rows:
        payload = r.structured_payload or {}
        title = (r.title or "")[:96]
        generic = title.startswith("Structural Impact Brief -")
        raw_feed = any(title.startswith(p) for p in feed_prefixes)
        tl = len(payload.get("event_timeline") or [])
        line = f"  {r.topic_code}: generic={generic} raw_feed={raw_feed} timeline={tl} title={title}"
        print(line.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
    if dupes:
        raise SystemExit(1)
    if any((r.title or "").startswith("Structural Impact Brief -") for r in rows):
        print("WARN: some titles still use legacy template prefix")


if __name__ == "__main__":
    asyncio.run(main())
