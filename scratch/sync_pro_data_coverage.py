import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.database import AsyncSessionLocal
from jobs.market_data_fetcher import MarketDataFetcher
from jobs.external_data_fetcher import ExternalDataFetcher

async def sync_coverage():
    async with AsyncSessionLocal() as db:
        print("=" * 70)
        print("SYNCING DATA COVERAGE FOR PRO REPORTS")
        print("=" * 70)

        # 1. Market Data (Energy focus + FX History)
        print("\n[1] Syncing Market Data (Domain: energy_resource_risk)...")
        mf = MarketDataFetcher(db)
        # Syncing energy domain instruments from catalog
        av_res = await mf.sync_alpha_vantage_sample(domain_id="energy_resource_risk")
        print(f"  Alpha Vantage Result: {av_res}")
        
        print("\n[2] Syncing Frankfurter FX History (30 Days)...")
        fk_res = await mf.sync_frankfurter_fx_history(days=31)
        print(f"  Frankfurter Result: {fk_res}")

        # 2. External Data (FRED / BLS for Energy)
        print("\n[3] Syncing External Data (Energy Series)...")
        ef = ExternalDataFetcher(db)
        
        # FRED: DCOILWTICO, GASREGW
        print("  Syncing FRED (DCOILWTICO, GASREGW)...")
        await ef.sync_fred(series_ids=["DCOILWTICO", "GASREGW"])
        
        # BLS: WPU05, WPU051
        print("  Syncing BLS (WPU05, WPU051)...")
        await ef.sync_bls(series_ids=["WPU05", "WPU051"])
        
        print("\n" + "=" * 70)
        print("SYNC COMPLETED")
        print("=" * 70)

if __name__ == "__main__":
    asyncio.run(sync_coverage())
