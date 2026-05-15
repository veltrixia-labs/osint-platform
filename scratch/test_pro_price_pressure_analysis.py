import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import AsyncSessionLocal
from data_sources.pro_price_pressure_analysis import (
    get_ppi_bea_mapping,
    analyze_price_pressure_vs_growth,
    get_price_pressure_summary
)

async def test_integrated_analysis():
    async with AsyncSessionLocal() as session:
        print("="*80)
        print("PRO INTEGRATED ANALYSIS: PPI vs BEA GROWTH (2018-2024)")
        print("="*80)
        
        # 1. Show Mapping
        mapping = get_ppi_bea_mapping()
        print(f"Mapped {len(mapping)} PPI Series to related industries.")

        # 2. Detailed Analysis
        results = await analyze_price_pressure_vs_growth(session)
        print(f"\n{'PPI Label':<35} | {'Latest':>8} | {'Date':<7} | {'PPI Cum %':>10} | {'BEA Code':<8} | {'Signal'}")
        print("-" * 110)
        
        for r in results:
            print(f"{r['ppi_label'][:35]:<35} | {r['ppi_latest_value']:>8.1f} | {r['ppi_latest_date']:<7} | {r['ppi_cumulative_pct']:>9.1f}% | {r['bea_industry_code']:<8} | {r['signal']}")

        # 3. Summary
        print("\n" + "="*80)
        print("PRO PRICE PRESSURE SUMMARY")
        print("="*80)
        summary = await get_price_pressure_summary(session)
        
        print("\n[HIGH RISK: Cost/Margin Pressure]")
        for s in summary['high_risk_series']:
            print(f"  - {s['ppi_label']} (Cum PPI: +{s['ppi_cumulative_pct']}%)")
            print(f"    Target: {s['bea_industry_code']} Growth: {s['bea_industry_growth_pct']}%")
            print(f"    Status: {s['signal']}")

        print("\n[EASING PRESSURE: Opportunity]")
        for s in summary['easing_pressure_series']:
            print(f"  - {s['ppi_label']} (YoY PPI: {s['ppi_yoy_pct']}%)")
            print(f"    Target: {s['bea_industry_code']} Growth: {s['bea_industry_growth_pct']}%")

        print("\n[PRICING POWER: Growth with Inflation]")
        for s in summary['pricing_power_series']:
            print(f"  - {s['ppi_label']} (YoY PPI: +{s['ppi_yoy_pct']}%)")
            print(f"    Target: {s['bea_industry_code']} Growth: {s['bea_industry_growth_pct']}%")

        print("\n" + "="*80)
        print("QUANTITATIVE INSIGHTS")
        print("="*80)
        # Find strongest cost pressure
        strongest = max(results, key=lambda x: x['ppi_cumulative_pct'] or 0)
        print(f"  1. Max Price Pressure: {strongest['ppi_label']} (+{strongest['ppi_cumulative_pct']}% since 2018).")
        
        # Check manufacturing
        mfg = [r for r in results if r['bea_industry_code'] == '31G']
        if mfg:
            print(f"  2. Manufacturing (31G) is exposed to multiple pressures: Goods PPI (+{mfg[0]['ppi_cumulative_pct']}%) vs Growth (+{mfg[0]['bea_industry_growth_pct']}%).")
            
        print(f"  3. Total Risks Detected: {summary['summary_metadata']['risk_count']} unique series indicating margin or cost stress.")

if __name__ == "__main__":
    asyncio.run(test_integrated_analysis())
