"""
Test script for Pro Structural Report Generator Pipeline.

Verifies:
1. End-to-end generation from domain_id.
2. DB persistence with correct flags (plan_required=pro, is_premium=True).
3. Markdown content verification.
"""

import asyncio
import sys
import os
import logging
from sqlalchemy import select, desc

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.pro_report_generator import run_pro_structural_report_generation
from db.models import Report

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_test():
    async with AsyncSessionLocal() as db:
        print("=" * 60)
        print("PRO REPORT GENERATOR PIPELINE TEST")
        print("=" * 60)

        # 1. Generate for Energy Resource Risk
        print("\n[1] Generating Energy Resource Risk report...")
        report = await run_pro_structural_report_generation(domain_id="energy_resource_risk")
        
        print(f"  Report ID: {report.id}")
        print(f"  Title: {report.title}")
        print(f"  Type: {report.report_type}")
        print(f"  Plan Required: {report.plan_required}")
        print(f"  Is Premium: {report.is_premium}")
        
        assert report.plan_required == "pro"
        assert report.is_premium is True
        assert "Structural Impact Brief" in report.title
        assert "Energy & Resource Risk" in report.title
        
        # 2. Content Verification
        print("\n[2] Verifying content sections...")
        content = report.content_markdown
        sections = [
            "Structural Impact Brief",
            "Market Relevance",
            "Quantitative Context",
            "Market Confirmation",
            "Watch Indicators",
            "Data Notes"
        ]
        for s in sections:
            assert s in content, f"Section '{s}' missing from content"
        print("  [OK] All sections found in Markdown.")

        # 3. Save Markdown to scratch
        output_path = "scratch/pro_report_saved_sample.md"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  [OK] Saved content to {output_path}")

        # 4. Generate for Global Market Intelligence
        print("\n[3] Generating Global Market Intelligence report...")
        report_global = await run_pro_structural_report_generation(domain_id="global_market_intelligence")
        print(f"  [OK] Global report generated: {report_global.title}")

    print("\n" + "=" * 60)
    print("Test completed successfully.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
