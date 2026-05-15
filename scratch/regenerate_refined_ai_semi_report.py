import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from analysis.pro_structural_context import build_pro_structural_context
from reports.pro_structural_report_builder import build_pro_structural_report

async def regenerate_refined_report():
    domain_id = "ai_semiconductor_intelligence"
    async with AsyncSessionLocal() as db:
        print(f"Generating REFINED Pro Structural Brief for Domain: {domain_id}...")
        
        # Use existing context engine
        context = await build_pro_structural_context(
            db, 
            domain_id=domain_id,
            lookback_days=30
        )
        
        # Generate Report
        report_md = build_pro_structural_report(context)
        
        # Save Report
        output_path = os.path.join("scratch", "pro_domain_ai_semiconductor_report_refined_v2.md")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_md)
            
        print(f"Refined report saved to: {output_path}")

if __name__ == "__main__":
    asyncio.run(regenerate_refined_report())
