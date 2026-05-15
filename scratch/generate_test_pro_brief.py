import asyncio
import sys
import os
import uuid
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import Report, AlertLog
from jobs.pro_report_generator import run_pro_structural_report_generation
from sqlalchemy import select, func

async def generate_and_verify():
    alert_id = "b0f36726-6ec1-4d85-820e-be9c804ab5ab"
    topic = "global_market_intelligence"
    output_path = "scratch/pro_real_generation_global_market_test.md"

    async with AsyncSessionLocal() as db:
        print("=" * 80)
        print("MANUAL PRO STRUCTURAL BRIEF GENERATION TEST")
        print("=" * 80)

        # 1. Record pre-generation count
        stmt_count = select(func.count(Report.id)).where(
            Report.report_type == "pro_structural",
            Report.plan_required == "pro",
            Report.is_premium == True
        )
        pre_count = (await db.execute(stmt_count)).scalar()
        print(f"Pre-generation Report Count: {pre_count}")

        # 2. Run generation
        print(f"\n[GENERATING] Alert ID: {alert_id}")
        try:
            report = await run_pro_structural_report_generation(
                alert_id=alert_id,
                domain_id=topic
            )
        except Exception as e:
            print(f"FAILED: {e}")
            return

        # 3. Record post-generation count
        post_count = (await db.execute(stmt_count)).scalar()
        print(f"Post-generation Report Count: {post_count}")

        # 4. Verify report details
        print(f"\n[VERIFYING] Report ID: {report.id}")
        print(f"  Title: {report.title}")
        print(f"  Type: {report.report_type}")
        print(f"  Topic Code: {report.topic_code}")
        print(f"  Plan Required: {report.plan_required}")
        print(f"  Is Premium: {report.is_premium}")
        
        content = report.content_markdown or ""
        print(f"  Content Length: {len(content)} characters")

        # 5. Save to scratch file
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\n[SAVED] Markdown saved to {output_path}")

        # 6. Basic Content Check
        print("\n[CONTENT ANALYSIS]")
        
        # Check for sections
        sections = {
            "Quantitative Context": "Quantitative Context" in content,
            "Market Confirmation": "Market Confirmation" in content,
            "Watch Indicators": "Watch Indicators" in content,
            "Data Notes": "Data Notes" in content or "Coverage Limitations" in content
        }
        for sec, found in sections.items():
            print(f"  {sec}: {'FOUND' if found else 'MISSING'}")

        # Check for symbols (Global Market)
        symbols = ["SPY", "QQQ", "TLT", "GLD", "USDJPY"]
        found_symbols = [s for s in symbols if s in content]
        print(f"  Market Symbols Found: {found_symbols}")

        # Check for indicators
        indicators = ["FEDFUNDS", "DGS10", "CPIAUCSL", "DTWEXBGS"]
        found_indicators = [i for i in indicators if i in content]
        print(f"  Macro Indicators Found: {found_indicators}")

        # Check Watch Indicators count
        # Assuming Watch Indicators are in a list or section with bullet points
        # This is a rough check
        watch_count = content.count("### Watch Indicator:") or content.count("#### Indicator:")
        # Let's check for specific pattern in the builder
        print(f"  Approximate Watch Indicators: {watch_count}")

        print("\n" + "=" * 80)
        print("Generation and verification complete.")

if __name__ == "__main__":
    asyncio.run(generate_and_verify())
