import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, or_

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AlertLog, Report
from jobs.pro_automation_manager import ProAutomationManager

async def run_scheduler_test():
    print("=" * 80)
    print("PRO AUTOMATION SCHEDULER TEST (REAL GENERATION)")
    print("=" * 80)

    async with AsyncSessionLocal() as db:
        # 1. Count current Pro Structural Briefs
        stmt_count = select(func.count(Report.id)).where(
            Report.plan_required == "pro",
            Report.is_premium == True,
            Report.report_type == "pro_structural"
        )
        before_count = (await db.execute(stmt_count)).scalar() or 0
        print(f"Pro Structural Briefs before: {before_count}")

        # 2. Setup Environment Variables (Temporary)
        os.environ["ENABLE_PRO_AUTOMATION"] = "true"
        os.environ["PRO_AUTOMATION_DRY_RUN"] = "false"
        os.environ["PRO_AUTOMATION_ENABLED_DOMAINS"] = "energy_resource_risk,ai_semiconductor_intelligence"
        os.environ["PRO_AUTOMATION_LIMIT"] = "1"

        # 3. Run ProAutomationManager.run_once
        print("\nExecuting ProAutomationManager.run_once(dry_run=False, limit=1)...")
        manager = ProAutomationManager(db)
        results = await manager.run_once(dry_run=False, limit=1)

        print("\n[MANAGER RESULTS]")
        print(f"  Candidates Found: {results['candidates_found']}")
        print(f"  Generated Count : {results['generated_count']}")
        print(f"  Skipped Count   : {results['skipped_count']}")
        
        # 4. Verify the results
        after_count = (await db.execute(stmt_count)).scalar() or 0
        print(f"\nPro Structural Briefs after: {after_count} (Change: +{after_count - before_count})")

        if results["generated_reports"]:
            print("\n[GENERATED REPORTS]")
            for rep_info in results["generated_reports"]:
                rep_id = rep_info.get("report_id")
                if not rep_id:
                     print(f"  Report generated but ID missing in results? Info: {rep_info}")
                     continue
                
                # Fetch full record
                stmt_rep = select(Report).where(Report.id == uuid.UUID(rep_id))
                report = (await db.execute(stmt_rep)).scalar_one_or_none()
                
                if report:
                    print(f"  Report ID    : {report.id}")
                    print(f"  Title        : {report.title}")
                    print(f"  Topic Code   : {report.topic_code}")
                    print(f"  Report Type  : {report.report_type}")
                    
                    has_content = bool(report.content_markdown and len(report.content_markdown) > 100)
                    has_market = "Market Confirmation" in report.content_markdown
                    has_quant = "Quantitative Context" in report.content_markdown
                    has_notes = "Data Notes" in report.content_markdown or "Coverage Limitations" in report.content_markdown

                    print(f"  Content Non-Empty: {has_content}")
                    print(f"  Market Confirmation: {has_market}")
                    print(f"  Quantitative Context: {has_quant}")
                    print(f"  Data Notes: {has_notes}")
                else:
                    print(f"  FAILED to find report record for ID: {rep_id}")

        if results["skipped"]:
            print("\n[SKIPPED DETAILS]")
            for skip in results["skipped"]:
                print(f"  Alert: {skip.get('alert_id')} | Reason: {skip.get('reason')}")

        if after_count - before_count > 1:
            print(f"\nWARNING: More than 1 report generated! ({after_count - before_count})")

if __name__ == "__main__":
    asyncio.run(run_scheduler_test())
