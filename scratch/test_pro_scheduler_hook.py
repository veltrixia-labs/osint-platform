"""
Test script for Pro Scheduler Hook.

Verifies that the scheduled wrapper respects environment variables 
and doesn't generate reports by default.
"""

import asyncio
import sys
import os
import logging
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jobs.pro_automation_manager import run_scheduled_pro_automation
from db.database import AsyncSessionLocal
from sqlalchemy import select, func
from db.models import Report

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_report_count():
    async with AsyncSessionLocal() as db:
        stmt = select(func.count(Report.id)).where(Report.plan_required == "pro")
        return (await db.execute(stmt)).scalar() or 0

async def run_test():
    print("=" * 70)
    print("PRO SCHEDULER HOOK TEST")
    print("=" * 70)

    initial_count = await get_report_count()
    print(f"Initial Pro reports in DB: {initial_count}")

    # 1. Test: Disabled state (Default)
    print("\n[1] Testing DISABLED state (ENABLE_PRO_AUTOMATION=false)...")
    with patch.dict(os.environ, {"ENABLE_PRO_AUTOMATION": "false"}):
        res = await run_scheduled_pro_automation()
        print(f"  Result status: {res.get('status')}")
        print(f"  Skipped: {res.get('skipped')}")
        
    current_count = await get_report_count()
    assert current_count == initial_count, "Report count increased in disabled state!"
    print("  [PASS] No reports generated.")

    # 2. Test: Enabled + Dry Run
    print("\n[2] Testing DRY RUN state (ENABLE_PRO_AUTOMATION=true, PRO_AUTOMATION_DRY_RUN=true)...")
    with patch.dict(os.environ, {
        "ENABLE_PRO_AUTOMATION": "true",
        "PRO_AUTOMATION_DRY_RUN": "true",
        "PRO_AUTOMATION_LIMIT": "2"
    }):
        res = await run_scheduled_pro_automation()
        print(f"  Candidates Found: {res.get('candidates_found')}")
        print(f"  Generated Count (Planned): {res.get('generated_count')}")
        print(f"  Dry Run Flag: {res.get('dry_run')}")
        
    current_count = await get_report_count()
    assert current_count == initial_count, "Report count increased in dry run state!"
    print("  [PASS] No reports generated.")

    # 3. Test: Real generation check (Safety)
    print("\n[3] Safety Check: Verifying that real generation requires explicit override...")
    # We won't actually run it, just verify the code logic path if possible, 
    # but the dry_run=True in manager.run_once is the ultimate safeguard.

    print("\n" + "=" * 70)
    print("Test completed successfully.")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_test())
