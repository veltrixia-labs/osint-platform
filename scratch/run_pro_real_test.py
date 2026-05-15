import asyncio
import sys
import os
import json
from datetime import datetime, timezone
from sqlalchemy import select, func

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AlertLog, Report
from jobs.pro_report_generator import run_pro_structural_report_generation

async def run_manual_test():
    alert_id = "9a79c1f8-979b-4e8d-ace8-569c2cb3478b"
    domain_id = "energy_resource_risk"
    output_path = "scratch/pro_real_generation_energy_test.md"

    async with AsyncSessionLocal() as db:
        # 1. Record current Pro Report count
        stmt_count = select(func.count(Report.id)).where(Report.plan_required == "pro")
        before_count = (await db.execute(stmt_count)).scalar() or 0
        print(f"Pro Reports count before: {before_count}")

        # 2. Generate the report
        print(f"Generating Pro Structural Brief for Alert: {alert_id}...")
        try:
            report = await run_pro_structural_report_generation(alert_id=alert_id)
            if not report:
                print("Failed to generate report (returned None).")
                return
        except Exception as e:
            print(f"Error during generation: {e}")
            import traceback
            traceback.print_exc()
            return

        # 3. Verify the generated report
        print("\n[VERIFICATION]")
        print(f"Report ID    : {report.id}")
        print(f"Title        : {report.title}")
        print(f"Topic Code   : {report.topic_code}")
        print(f"Report Type  : {report.report_type}")
        print(f"Plan Required: {report.plan_required}")
        print(f"Is Premium   : {report.is_premium}")
        
        has_content = bool(report.content_markdown and len(report.content_markdown) > 100)
        has_market = "## 2. Market Confirmation" in report.content_markdown or "Market Confirmation" in report.content_markdown
        has_quant = "## 3. Quantitative Context" in report.content_markdown or "Quantitative Context" in report.content_markdown
        has_notes = "Data Notes" in report.content_markdown or "Coverage Limitations" in report.content_markdown

        print(f"Content Non-Empty: {has_content}")
        print(f"Market Confirmation Found: {has_market}")
        print(f"Quantitative Context Found: {has_quant}")
        print(f"Data Notes Found: {has_notes}")

        # 4. Save Markdown
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report.content_markdown)
        print(f"Markdown saved to: {output_path}")

        # 5. Verify count increase
        after_count = (await db.execute(stmt_count)).scalar() or 0
        print(f"Pro Reports count after: {after_count} (Change: +{after_count - before_count})")

        # 6. Check for duplicates
        stmt_dup = select(Report).where(
            Report.topic_code == domain_id,
            Report.report_type == "pro_structural",
            Report.created_at >= datetime.now(timezone.utc) - datetime.timedelta(minutes=5)
        )
        recent_reps = (await db.execute(stmt_dup)).scalars().all()
        if len(recent_reps) > 1:
            print(f"WARNING: Multiple reports generated ({len(recent_reps)})!")
            for r in recent_reps:
                print(f"  - ID: {r.id} | Created: {r.created_at}")
        
        # Extract specific sections for report
        content = report.content_markdown
        market_section = ""
        quant_section = ""
        notes_section = ""

        # Simple extraction logic
        if "## 2. Market Confirmation" in content:
            market_section = content.split("## 2. Market Confirmation")[1].split("##")[0].strip()
        if "## 3. Quantitative Context" in content:
            quant_section = content.split("## 3. Quantitative Context")[1].split("##")[0].strip()
        if "### Data Notes" in content:
            notes_section = content.split("### Data Notes")[1].split("##")[0].strip()
        elif "Coverage Limitations" in content:
             notes_section = content.split("Coverage Limitations")[1].split("##")[0].strip()

        print("\n[EXTRACTED SECTIONS]")
        print("--- Market Confirmation ---")
        print(market_section[:300] + "...")
        print("\n--- Quantitative Context ---")
        print(quant_section[:300] + "...")
        print("\n--- Data Notes ---")
        print(notes_section[:300] + "...")

if __name__ == "__main__":
    asyncio.run(run_manual_test())
