"""
Cleanup-first: DELETE all Pro Structural Brief rows, then run the rule-based compiler.

No LLM calls — uses jobs.pro_realtime_stream (quantitative DB matrices + OSINT signals).

Usage:
  py -u scratch/purge_and_regenerate_pro_insights.py --confirm
  py -u scratch/purge_and_regenerate_pro_insights.py --confirm --purge-only
  py -u scratch/purge_and_regenerate_pro_insights.py --confirm --generate-only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

from db.database import AsyncSessionLocal
from jobs.pro_realtime_stream import run_continuous_pro_intelligence_stream
from jobs.pro_structural_retention import count_all_pro_structural_reports, run_pro_structural_full_purge


def _log(msg: str) -> None:
    print(msg, flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fast purge + rule-based Pro Structural Brief compile (no LLM).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to DELETE rows and compile fresh briefs.",
    )
    parser.add_argument("--purge-only", action="store_true", help="Only DELETE; skip compile.")
    parser.add_argument("--generate-only", action="store_true", help="Skip DELETE; compile only.")
    args = parser.parse_args()

    t0 = time.perf_counter()
    dry_run = not args.confirm
    if dry_run:
        _log("[DRY RUN] Pass --confirm to execute.")

    async with AsyncSessionLocal() as db:
        before = await count_all_pro_structural_reports(db)
        _log(f"pro_structural rows before: {before}")

        if not args.generate_only:
            purge = await run_pro_structural_full_purge(db, dry_run=dry_run)
            _log(f"purge: {purge}")
            after = await count_all_pro_structural_reports(db)
            _log(f"pro_structural rows after purge: {after}")

    if not args.purge_only and args.confirm:
        _log("Compiling fresh briefs (rule-based stream, 6 domains)...")
        stream = await run_continuous_pro_intelligence_stream()
        _log(
            f"compile: status={stream.get('status')} "
            f"inserted={stream.get('inserted_count')} "
            f"elapsed_sec={stream.get('elapsed_sec', 0):.2f}"
        )
        if stream.get("errors"):
            _log(f"errors: {stream['errors']}")

        async with AsyncSessionLocal() as db:
            final = await count_all_pro_structural_reports(db)
            _log(f"pro_structural rows after compile: {final}")

    _log(f"total wall time: {time.perf_counter() - t0:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
