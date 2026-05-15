"""
Test script for Pro Domain Configuration.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analysis.pro_domain_config import (
    PRO_DOMAIN_CONFIG,
    get_all_pro_domains,
    get_pro_domain_config,
    get_domain_data_requirements,
    infer_domain_from_topic,
    get_market_symbols_for_domain
)

def run_test():
    print("=" * 60)
    print("PRO DOMAIN CONFIG TEST")
    print("=" * 60)

    # 1. Check all 6 domains
    domains = get_all_pro_domains()
    print(f"\n[1] Found domains: {domains}")
    assert len(domains) == 6, f"Expected 6 domains, found {len(domains)}"
    print("  [OK] 6 domains defined.")

    # 2. Check each domain for core fields
    print("\n[2] Verifying core fields for all domains...")
    for d_id in domains:
        config = get_pro_domain_config(d_id)
        assert config["domain_id"] == d_id
        assert "display_name" in config
        assert "primary_asset_classes" in config
        assert "structural_data" in config
        assert "market_data" in config
        assert len(config["watch_indicators"]) >= 1
        print(f"  [OK] {d_id} verified.")

    # 3. Check specific symbols for Energy
    print("\n[3] Verifying Energy Resource Risk symbols...")
    energy_req = get_domain_data_requirements("energy_resource_risk")
    av_symbols = energy_req["market"]["alpha_vantage_symbols"]
    inst_symbols = energy_req["market"]["instrument_symbols"]
    
    assert "XLE" in av_symbols
    assert "USO" in av_symbols
    assert "DCOILWTICO" in inst_symbols
    assert "WPU05" in inst_symbols
    assert "2709" in energy_req["structural"]["comtrade_commodity_codes"]
    print("  [OK] Energy symbols verified.")

    # 4. Check specific symbols for AI/Semi
    print("\n[4] Verifying AI/Semi symbols...")
    semi_req = get_domain_data_requirements("ai_semiconductor_intelligence")
    assert "SMH" in semi_req["market"]["alpha_vantage_symbols"]
    assert "SOXX" in semi_req["market"]["alpha_vantage_symbols"]
    assert "8542" in semi_req["structural"]["comtrade_commodity_codes"]
    print("  [OK] AI/Semi symbols verified.")

    # 5. Check specific symbols for Crypto
    print("\n[5] Verifying Crypto symbols...")
    crypto_req = get_domain_data_requirements("crypto_geopolitics")
    assert "BTC" in crypto_req["market"]["alpha_vantage_symbols"]
    assert "ETH" in crypto_req["market"]["alpha_vantage_symbols"]
    assert "DTWEXBGS" in crypto_req["market"]["instrument_symbols"]
    print("  [OK] Crypto symbols verified.")

    # 6. Check helper functions
    print("\n[6] Testing helper functions...")
    assert infer_domain_from_topic("supply_chain_intelligence") == "supply_chain_intelligence"
    assert infer_domain_from_topic("semi") == "ai_semiconductor_intelligence"
    
    global_req = get_domain_data_requirements("global_market_intelligence")
    assert "structural" in global_req and "market" in global_req
    print("  [OK] Helpers verified.")

    print("\n" + "=" * 60)
    print("Test completed successfully.")
    print("=" * 60)

if __name__ == "__main__":
    run_test()
