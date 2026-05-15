"""
Test script for Pro Structural Context Engine.
"""

import asyncio
import sys
import os
import json
import logging

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from analysis.pro_structural_context import build_pro_structural_context

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_test():
    async with AsyncSessionLocal() as db:
        print("=" * 60)
        print("PRO STRUCTURAL CONTEXT ENGINE TEST")
        print("=" * 60)

        # 1. Test Energy Resource Risk
        print("\n[1] Building context for 'energy_resource_risk'...")
        ctx_energy = await build_pro_structural_context(db, domain_id="energy_resource_risk")
        
        print(f"Domain: {ctx_energy['domain']['display_name']}")
        print(f"Macro Obs Count: {len(ctx_energy['structural_context']['macro_observations'])}")
        print(f"Trade Flows Count: {len(ctx_energy['structural_context']['trade_flows'])}")
        print(f"Market Prices Count: {len(ctx_energy['market_confirmation']['latest_prices'])}")
        
        # Verify specific keys
        macro_ids = [o['series_id'] for o in ctx_energy['structural_context']['macro_observations']]
        print(f"Found Macro IDs: {macro_ids}")
        
        market_symbols = [p['symbol'] for p in ctx_energy['market_confirmation']['latest_prices']]
        print(f"Found Market Symbols: {market_symbols}")

        # 2. Test Global Market Intelligence
        print("\n[2] Building context for 'global_market_intelligence'...")
        ctx_global = await build_pro_structural_context(db, domain_id="global_market_intelligence")
        print(f"Domain: {ctx_global['domain']['display_name']}")
        print(f"Macro Obs Count: {len(ctx_global['structural_context']['macro_observations'])}")
        
        # 3. Save sample output
        output_path = "scratch/pro_structural_context_sample.json"
        # Use a simplified version for JSON saving (remove raw_json for readability)
        serializable_ctx = ctx_energy.copy()
        for obs in serializable_ctx['structural_context']['macro_observations']:
            obs['raw_json'] = "...(omitted)..."
            
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(serializable_ctx, f, indent=2, ensure_ascii=False)
        
        print(f"\n[OK] Sample context saved to {output_path}")

        # 4. Check Data Notes
        if ctx_energy['data_notes']:
            print("\nData Notes:")
            for note in ctx_energy['data_notes']:
                print(f"  - {note}")

    print("\n" + "=" * 60)
    print("Test completed.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
