import asyncio
import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.database import AsyncSessionLocal
from jobs.pro_report_generator import run_pro_structural_report_generation
from db.models import Report

async def generate_test_report():
    alert_id = "1c792655-163b-4c21-a7e4-cbf6940754db"
    print(f"Generating Pro Structural Brief for Alert: {alert_id}...")
    
    try:
        report = await run_pro_structural_report_generation(
            alert_id=alert_id,
            domain_id="energy_resource_risk",
            report_type="weekly"
        )
        
        print("\n" + "=" * 70)
        print("REPORT GENERATED SUCCESSFULLY")
        print("=" * 70)
        print(f"Report ID: {report.id}")
        print(f"Title: {report.title}")
        print(f"Plan: {report.plan_required}")
        print(f"Premium: {report.is_premium}")
        
        # Save content to scratch file
        output_path = os.path.join("scratch", "pro_live_test_report_after_coverage_fix.md")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report.content_markdown)
        
        print(f"\nReport content saved to: {output_path}")
        
        # Quick verification of sections
        content = report.content_markdown
        has_market = "## 5. Market Confirmation" in content
        has_quant = "## 4. Quantitative Context" in content
        has_notes = "## 9. Data Notes" in content
        
        print(f"Section Verification:")
        print(f" - Market Confirmation: {'[OK]' if has_market else '[MISSING]'}")
        print(f" - Quantitative Context: {'[OK]' if has_quant else '[MISSING]'}")
        print(f" - Data Notes: {'[OK]' if has_notes else '[MISSING]'}")
        
    except Exception as e:
        print(f"Error during report generation: {e}")

if __name__ == "__main__":
    asyncio.run(generate_test_report())
