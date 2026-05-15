import asyncio
import sys
import os
import shutil
from datetime import datetime, timezone
from sqlalchemy import select, func, desc

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import Report
from jobs.pro_automation_manager import ProAutomationManager

async def run_single_production_cycle():
    env_path = ".env"
    backup_path = ".env.bak"
    
    async with AsyncSessionLocal() as db:
        # 1. Count current Pro Structural Briefs
        stmt_count = select(func.count(Report.id)).where(
            Report.plan_required == "pro",
            Report.is_premium == True,
            Report.report_type == "pro_structural"
        )
        before_count = (await db.execute(stmt_count)).scalar() or 0
        print(f"Pro Structural Briefs count before: {before_count}")

        # 2. Backup and Modify .env
        print("Backing up .env and switching DRY_RUN to false...")
        shutil.copy(env_path, backup_path)
        
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        new_lines = []
        for line in lines:
            if line.startswith("PRO_AUTOMATION_DRY_RUN="):
                new_lines.append("PRO_AUTOMATION_DRY_RUN=false\n")
            elif line.startswith("PRO_AUTOMATION_LIMIT="):
                new_lines.append("PRO_AUTOMATION_LIMIT=1\n")
            elif line.startswith("PRO_AUTOMATION_ENABLED_DOMAINS="):
                new_lines.append("PRO_AUTOMATION_ENABLED_DOMAINS=energy_resource_risk,ai_semiconductor_intelligence\n")
            else:
                new_lines.append(line)
        
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        # 3. Run ProAutomationManager.run_once
        print("Executing ProAutomationManager.run_once(dry_run=False, limit=1)...")
        manager = ProAutomationManager(db)
        results = await manager.run_once(limit=1, dry_run=False)
        
        print("\n[EXECUTION RESULTS]")
        print(f"Candidates Found   : {results['candidates_found']}")
        print(f"Generated Count    : {results['generated_count']}")
        print(f"Skipped Count      : {results['skipped_count']}")
        
        for r in results['generated_reports']:
            print(f"  - Generated: {r['title']} (ID: {r.get('report_id')})")
        for s in results['skipped']:
            print(f"  - Skipped: Alert {s['alert_id']} | Reason: {s['reason']}")

        # 4. Verify count increase
        after_count = (await db.execute(stmt_count)).scalar() or 0
        print(f"\nPro Structural Briefs count after: {after_count} (Change: +{after_count - before_count})")

        # 5. Restore .env
        print("\nRestoring .env from backup...")
        shutil.copy(backup_path, env_path)
        os.remove(backup_path)

        # 6. Final verification of the latest report if generated
        if after_count > before_count:
            stmt_latest = select(Report).where(
                Report.report_type == "pro_structural"
            ).order_by(desc(Report.created_at)).limit(1)
            latest = (await db.execute(stmt_latest)).scalar()
            
            print("\n[LATEST REPORT DETAILS]")
            print(f"Report ID: {latest.id}")
            print(f"Title    : {latest.title}")
            print(f"Type     : {latest.report_type}")
            
            has_market = "Market Confirmation" in latest.content_markdown
            has_quant = "Quantitative Context" in latest.content_markdown
            has_notes = "Data Notes" in latest.content_markdown or "Coverage Limitations" in latest.content_markdown
            
            print(f"Market Confirmation: {'YES' if has_market else 'NO'}")
            print(f"Quantitative Context: {'YES' if has_quant else 'NO'}")
            print(f"Data Notes: {'YES' if has_notes else 'NO'}")

if __name__ == "__main__":
    asyncio.run(run_single_production_cycle())
