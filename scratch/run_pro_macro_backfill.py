"""
CLI: force Pro macro + market sync (local / production DB via DATABASE_URL).

  py scratch/run_pro_macro_backfill.py
  py scratch/run_pro_macro_backfill.py --rebuild
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jobs.external_data_sync import run_pro_macro_data_sync
from jobs.pro_brief_regenerator import run_pro_platform_rebuild


async def main() -> None:
    parser = argparse.ArgumentParser(description="Pro macro backfill + optional full rebuild")
    parser.add_argument("--rebuild", action="store_true", help="Sync then purge+regenerate briefs")
    parser.add_argument("--full", action="store_true", help="Run full external sync pipeline")
    args = parser.parse_args()

    if args.rebuild:
        result = await run_pro_platform_rebuild(
            purge_first=True,
            sync_macro_first=True,
            full_macro_pipeline=args.full,
        )
    else:
        result = await run_pro_macro_data_sync(
            full_pipeline=args.full,
            skip_inter_step_delay=True,
            sync_market_data=True,
        )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
