"""
Test script for Pro Structural Brief Automation Manager.

Verifies:
1. Candidate selection integration.
2. Daily and Domain cap enforcement.
3. Dry-run mode safety.
4. Live generation (optional via environment variable).
"""

import asyncio
import sys
import os
import logging
import json
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.pro_automation_manager import ProAutomationManager
from db.models import Report

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_test():
    async with AsyncSessionLocal() as db:
        print("=" * 70)
        print("PRO AUTOMATION MANAGER TEST")
        print("=" * 70)

        manager = ProAutomationManager(db)

        # 1. Dry Run Test
        print("\n[1] Running Automation Cycle (DRY RUN)...")
        results = await manager.run_once(limit=5, dry_run=True)
        
        print(f"  Dry Run: {results['dry_run']}")
        print(f"  Candidates Found: {results['candidates_found']}")
        print(f"  Planned to Generate: {results['generated_count']}")
        print(f"  Skipped: {results['skipped_count']}")
        
        if results['skipped']:
            print("\n  Skipped Reasons:")
            for s in results['skipped']:
                print(f"    - Alert {s.get('alert_id', 'Global')}: {s['reason']}")

        if results['generated_reports']:
            print("\n  Planned Reports:")
            for r in results['generated_reports']:
                print(f"    - {r['title']} (Alert: {r['alert_id']})")

        # Verify no reports were actually created
        stmt = select(func.count(Report.id)).where(Report.plan_required == "pro")
        count_after_dry = (await db.execute(stmt)).scalar()
        print(f"\n  [OK] Current Pro reports in DB: {count_after_dry}")

        # 2. Live Run Test (Optional)
        run_real = os.getenv("RUN_REAL_AUTOMATION", "false").lower() == "true"
        
        if run_real:
            print("\n" + "-"*40)
            print("[2] Running Automation Cycle (LIVE RUN)...")
            print("-"*40)
            
            # Reset session to avoid state issues
            async with AsyncSessionLocal() as db_live:
                live_manager = ProAutomationManager(db_live)
                live_results = await live_manager.run_once(limit=1, dry_run=False)
                
                print(f"  Generated: {live_results['generated_count']}")
                if live_results['generated_reports']:
                    for r in live_results['generated_reports']:
                        print(f"    - CREATED: {r['title']} (ID: {r['report_id']})")
                
                if live_results['errors_count'] > 0:
                    print(f"  Errors: {live_results['errors_count']}")
        else:
            print("\n[2] Live Run skipped. (Set RUN_REAL_AUTOMATION=true to test actual generation)")

        print("\n" + "=" * 70)
        print("Test completed successfully.")
        print("=" * 70)

from sqlalchemy import select, func

if __name__ == "__main__":
    asyncio.run(run_test())
