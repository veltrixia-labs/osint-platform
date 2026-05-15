import asyncio
import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.database import AsyncSessionLocal
from jobs.market_data_fetcher import MarketDataFetcher
from jobs.external_data_fetcher import ExternalDataFetcher

DOMAINS = [
    "global_market_intelligence",
    "ai_semiconductor_intelligence",
    "defense_technology",
    "supply_chain_intelligence",
    "crypto_geopolitics",
    "energy_resource_risk"
]

async def sync_all_coverage():
    async with AsyncSessionLocal() as db:
        print("=" * 70)
        print("SYNCING FULL DATA COVERAGE FOR ALL PRO DOMAINS")
        print("=" * 70)

        mf = MarketDataFetcher(db)
        ef = ExternalDataFetcher(db)

        # 1. Market Data (Domain by Domain to respect AV limits)
        for domain_id in DOMAINS:
            print(f"\n[*] Syncing Market Data for Domain: {domain_id}...")
            res = await mf.sync_alpha_vantage_sample(domain_id=domain_id)
            print(f"  Result: {res}")
            # Wait between domains to be safe (though fetcher has internal wait)
            await asyncio.sleep(5)

        print("\n[*] Syncing Frankfurter FX History (30 Days)...")
        fk_res = await mf.sync_frankfurter_fx_history(days=31)
        print(f"  Frankfurter Result: {fk_res}")

        # 2. External Data (Targeted Sync)
        print("\n[*] Syncing FRED Macro Series...")
        # Get all IDs from catalog to be sure
        from data_sources.fred_series_catalog import get_fred_series_ids
        fred_ids = get_fred_series_ids()
        await ef.sync_fred(series_ids=fred_ids)
        
        print("\n[*] Syncing BLS PPI Series...")
        from data_sources.bls_series_catalog import get_bls_series_ids
        bls_ids = get_bls_series_ids()
        await ef.sync_bls(series_ids=bls_ids)
        
        print("\n[*] Syncing World Bank Indicators (Sample)...")
        await ef.sync_worldbank()

        print("\n" + "=" * 70)
        print("FULL SYNC COMPLETED")
        print("=" * 70)

if __name__ == "__main__":
    asyncio.run(sync_all_coverage())
