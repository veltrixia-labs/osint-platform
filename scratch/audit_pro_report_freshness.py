"""
CLI: audit pro_structural reports in the connected database.

  py scratch/audit_pro_report_freshness.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.pro_brief_regenerator import audit_pro_structural_reports


async def main() -> None:
    async with AsyncSessionLocal() as db:
        audit = await audit_pro_structural_reports(db)
    print(json.dumps(audit, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
