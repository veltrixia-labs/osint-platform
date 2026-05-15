import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.pro_report_generator import run_pro_structural_report_generation

async def regenerate_report():
    alert_id = "b0f36726-6ec1-4d85-820e-be9c804ab5ab"
    topic = "global_market_intelligence"
    output_path = "scratch/pro_real_generation_global_market_test_refined.md"

    print("=" * 80)
    print("REGENERATING REFINED PRO STRUCTURAL BRIEF")
    print("=" * 80)

    try:
        report = await run_pro_structural_report_generation(
            alert_id=alert_id,
            domain_id=topic
        )
        
        content = report.content_markdown or ""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\n[SAVED] Refined markdown saved to {output_path}")
        print(f"Report ID: {report.id}")
        
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(regenerate_report())
