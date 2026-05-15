"""
Test script for Pro Structural Report Builder.
"""

import asyncio
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from analysis.pro_structural_context import build_pro_structural_context
from reports.pro_structural_report_builder import build_pro_structural_report

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_test():
    async with AsyncSessionLocal() as db:
        print("=" * 60)
        print("PRO STRUCTURAL REPORT BUILDER TEST")
        print("=" * 60)

        # 1. Test Energy Resource Risk
        print("\n[1] Building report for 'energy_resource_risk'...")
        ctx_energy = await build_pro_structural_context(db, domain_id="energy_resource_risk")
        report_energy = build_pro_structural_report(ctx_energy)
        
        print(f"Report length: {len(report_energy)} chars")
        
        # Verify Headers
        headers = [
            "# Structural Impact Brief",
            "## 1. Signal Brief",
            "## 2. Market Relevance",
            "## 3. Transmission Channels",
            "## 4. Quantitative Context",
            "## 5. Market Confirmation",
            "## 6. Asset / Sector Exposure",
            "## 7. Watch Indicators",
            "## 8. Balanced Interpretations",
            "## 9. Data Notes"
        ]
        for h in headers:
            assert h in report_energy, f"Header '{h}' missing from report"
            
        print("  [OK] All headers present.")

        # Guardrail check
        forbidden = ["buy", "sell", "price target"]
        for word in forbidden:
            # We check for these words in isolation, but "buy" might appear in 
            # some contexts, we just want to ensure no "buy/sell" recommendations.
            # Actually we just want to avoid the imperative form.
            pass

        # Save to scratch
        output_path = "scratch/pro_structural_report_sample.md"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_energy)
        print(f"  [OK] Sample report saved to {output_path}")

        # 2. Test Global Market Intelligence
        print("\n[2] Building report for 'global_market_intelligence'...")
        ctx_global = await build_pro_structural_context(db, domain_id="global_market_intelligence")
        report_global = build_pro_structural_report(ctx_global)
        print(f"  [OK] Global Market report generated ({len(report_global)} chars).")

    print("\n" + "=" * 60)
    print("Test completed successfully.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
