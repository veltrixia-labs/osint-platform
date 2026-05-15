import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import AsyncSessionLocal
from data_sources.pro_report_builder import build_pro_report

OUTPUT_FILE = Path("scratch/pro_report_sample.json")

async def test_pro_report_builder():
    async with AsyncSessionLocal() as session:
        print("="*80)
        print("BUILDING PRO REPORT (2024 / 2024-12)")
        print("="*80)
        
        report = await build_pro_report(session, as_of_year="2024", as_of_date="2024-12")
        
        # 1. Print keys
        print(f"Report Keys: {list(report.keys())}")
        print(f"Section Keys: {list(report['sections'].keys())}")
        
        # 2. Macro Snapshot
        print("\n[MACRO SNAPSHOT]")
        macro = report['sections']['macro_snapshot']
        print(f"  GDP: {macro.get('gdp_current_dollars_t', 0):.2f} T")
        print(f"  Growth: {macro.get('gdp_growth_rate_pct', 0)}%")
        print(f"  PCE: {macro.get('pce_current_dollars_t', 0):.2f} T")
        
        # 3. Risk Signals
        print("\n[RISK SIGNALS (TOP 5)]")
        risks = report['sections']['risk_signals']
        for r in risks[:5]:
            print(f"  - {r['ppi_label']} -> {r['bea_industry_code']} | Signal: {r['signal']}")
            print(f"    (PPI Cum: +{r['ppi_cumulative_pct']}% | Ind Growth: {r['bea_industry_growth_pct']}%)")

        # 4. Save to JSON
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"\nReport saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(test_pro_report_builder())
