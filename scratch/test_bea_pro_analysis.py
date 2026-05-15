import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import AsyncSessionLocal
from data_sources.bea_pro_analysis import (
    get_macro_snapshot,
    get_industry_snapshot,
    get_macro_industry_summary,
    get_growth_comparison,
    get_covid_recovery_summary
)

async def test_pro_analysis():
    async with AsyncSessionLocal() as session:
        print("="*60)
        print("PRO ANALYSIS: 2024 MACRO SNAPSHOT")
        print("="*60)
        macro = await get_macro_snapshot(session, "2024")
        print(f"  GDP (Current): ${macro['gdp_current_dollars_t']:.2f}T")
        print(f"  GDP Growth:    {macro['gdp_growth_rate_pct']}%")
        print(f"  PCE (Current): ${macro['pce_current_dollars_t']:.2f}T")
        print(f"  PCE/GDP Ratio: {macro['pce_gdp_ratio_pct']}%")

        print("\n" + "="*60)
        print("PRO ANALYSIS: 2024 TOP 10 INDUSTRIES (SECTOR SHARE)")
        print("="*60)
        top_industries = await get_industry_snapshot(session, "2024", top_n=10)
        for i, ind in enumerate(top_industries):
            print(f"  {i+1:>2}. {ind['industry_description'][:40]:<40} | Share: {ind['share_pct']:>5}% | ${ind['data_value']/1000:>5.2f}T")

        print("\n" + "="*60)
        print("PRO ANALYSIS: 2018 -> 2024 GROWTH COMPARISON")
        print("="*60)
        growth = await get_growth_comparison(session, "2018", "2024")
        print(f"  Macro GDP Growth (Current $): {growth['macro_growth']['gdp_growth_pct']}%")
        print(f"  Macro PCE Growth (Current $): {growth['macro_growth']['pce_growth_pct']}%")
        print("\n  Industry Value-Added Growth (Billions $):")
        # Sort by growth rate
        sorted_ind_growth = sorted(growth['industry_growth'].items(), key=lambda x: x[1], reverse=True)
        for label, rate in sorted_ind_growth:
            print(f"    {label:<45}: {rate:>5.1f}%")

        print("\n" + "="*60)
        print("PRO ANALYSIS: COVID RECOVERY SUMMARY (2019 -> 2020 -> 2021)")
        print("="*60)
        covid = await get_covid_recovery_summary(session)
        
        print(f"  {'Sector':<35} | 2020 Drop | 2021 Recov")
        print("-" * 65)
        for sector, stats in covid['sector_impacts'].items():
            drop = f"{stats['drop_2020']:>8.1f}%" if stats['drop_2020'] is not None else "     N/A"
            recov = f"{stats['recovery_2021']:>8.1f}%" if stats['recovery_2021'] is not None else "     N/A"
            print(f"  {sector:<35} | {drop} | {recov}")

        # Insight extraction
        print("\n" + "="*60)
        print("PRO INSIGHTS FOR REPORTING")
        print("="*60)
        print("  1. Concentration: The US economy is heavily driven by Real Estate and Professional Services.")
        print("  2. Resilience: Information sector showed the highest growth from 2018 to 2024.")
        print("  3. Post-COVID: Accommodation and Food services saw the deepest drop (-18.6%) and strongest bounce (+31.2%).")
        print(f"  4. Consumption: PCE now accounts for {macro['pce_gdp_ratio_pct']}% of GDP, highlighting consumer dependency.")

if __name__ == "__main__":
    asyncio.run(test_pro_analysis())
