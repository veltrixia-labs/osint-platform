"""
Market Instrument Catalog.

Defines the symbols and instruments used for Market Confirmation in 
Pro Structural Briefs, mapped by intelligence domain.
"""

from typing import Dict, List, Any

MARKET_INSTRUMENT_DEFINITIONS = [
    # Energy
    {"symbol": "XLE", "name": "Energy Select Sector SPDR Fund", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["energy_resource_risk"]},
    {"symbol": "XOP", "name": "S&P Oil & Gas Exploration & Production ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["energy_resource_risk"]},
    {"symbol": "USO", "name": "United States Oil Fund LP", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["energy_resource_risk", "global_market_intelligence"]},
    {"symbol": "IYT", "name": "iShares US Transportation ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["energy_resource_risk", "supply_chain_intelligence"]},
    {"symbol": "JETS", "name": "U.S. Global Jets ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["energy_resource_risk"]},
    {"symbol": "N225", "name": "Nikkei 225", "asset_class": "index", "provider": "alpha_vantage", "domain_ids": ["energy_resource_risk", "global_market_intelligence"]},
    {"symbol": "DAX", "name": "DAX Index", "asset_class": "index", "provider": "alpha_vantage", "domain_ids": ["energy_resource_risk", "global_market_intelligence"]},
    {"symbol": "EWJ", "name": "iShares MSCI Japan ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["energy_resource_risk", "global_market_intelligence", "ai_semiconductor_intelligence"]},
    {"symbol": "EWG", "name": "iShares MSCI Germany ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["energy_resource_risk", "global_market_intelligence"]},
    
    # Global / Macro
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["global_market_intelligence", "crypto_geopolitics"]},
    {"symbol": "QQQ", "name": "Invesco QQQ Trust", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["global_market_intelligence", "ai_semiconductor_intelligence", "crypto_geopolitics"]},
    {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["global_market_intelligence"]},
    {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["global_market_intelligence", "crypto_geopolitics"]},
    {"symbol": "SHY", "name": "iShares 1-3 Year Treasury Bond ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["global_market_intelligence"]},
    {"symbol": "GLD", "name": "SPDR Gold Shares", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["global_market_intelligence"]},
    {"symbol": "VIX", "name": "CBOE Volatility Index", "asset_class": "index", "provider": "alpha_vantage", "domain_ids": ["global_market_intelligence"]},
    
    # AI / Semi
    {"symbol": "SMH", "name": "VanEck Semiconductor ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["ai_semiconductor_intelligence"]},
    {"symbol": "SOXX", "name": "iShares Semiconductor ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["ai_semiconductor_intelligence"]},
    {"symbol": "EWJ", "name": "iShares MSCI Japan ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["ai_semiconductor_intelligence"]},
    {"symbol": "EWY", "name": "iShares MSCI South Korea ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["ai_semiconductor_intelligence"]},
    
    # Defense
    {"symbol": "ITA", "name": "iShares U.S. Aerospace & Defense ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["defense_technology"]},
    {"symbol": "XAR", "name": "SPDR S&P Aerospace & Defense ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["defense_technology"]},
    {"symbol": "PPA", "name": "Invesco Aerospace & Defense ETF", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["defense_technology"]},
    
    # Supply Chain
    {"symbol": "XLI", "name": "Industrial Select Sector SPDR Fund", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["supply_chain_intelligence", "defense_technology"]},
    {"symbol": "XLB", "name": "Materials Select Sector SPDR Fund", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["supply_chain_intelligence"]},
    {"symbol": "CARZ", "name": "First Trust Nasdaq Global Auto Index Fund", "asset_class": "equity", "provider": "alpha_vantage", "domain_ids": ["supply_chain_intelligence"]},
    
    # Crypto
    {"symbol": "BTC", "name": "Bitcoin", "asset_class": "crypto", "provider": "alpha_vantage", "domain_ids": ["crypto_geopolitics"], "quote_currency": "USD"},
    {"symbol": "ETH", "name": "Ethereum", "asset_class": "crypto", "provider": "alpha_vantage", "domain_ids": ["crypto_geopolitics"], "quote_currency": "USD"},
    
    # FX
    {"symbol": "USDCAD", "name": "USD / CAD", "asset_class": "fx", "provider": "frankfurter", "domain_ids": ["energy_resource_risk"], "base_currency": "USD", "quote_currency": "CAD"},
    {"symbol": "USDNOK", "name": "USD / NOK", "asset_class": "fx", "provider": "frankfurter", "domain_ids": ["energy_resource_risk"], "base_currency": "USD", "quote_currency": "NOK"},
    {"symbol": "USDBRL", "name": "USD / BRL", "asset_class": "fx", "provider": "frankfurter", "domain_ids": ["energy_resource_risk"], "base_currency": "USD", "quote_currency": "BRL"},
    {"symbol": "USDJPY", "name": "USD / JPY", "asset_class": "fx", "provider": "frankfurter", "domain_ids": ["energy_resource_risk", "ai_semiconductor_intelligence", "global_market_intelligence"], "base_currency": "USD", "quote_currency": "JPY"},
    {"symbol": "EURUSD", "name": "EUR / USD", "asset_class": "fx", "provider": "frankfurter", "domain_ids": ["energy_resource_risk", "global_market_intelligence"], "base_currency": "EUR", "quote_currency": "USD"},
    {"symbol": "GBPUSD", "name": "GBP / USD", "asset_class": "fx", "provider": "frankfurter", "domain_ids": ["global_market_intelligence"], "base_currency": "GBP", "quote_currency": "USD"},
    {"symbol": "USDCNY", "name": "USD / CNY", "asset_class": "fx", "provider": "alpha_vantage", "domain_ids": ["supply_chain_intelligence"], "base_currency": "USD", "quote_currency": "CNY"},
]

def get_instruments_for_domain(domain_id: str) -> List[Dict[str, Any]]:
    """Returns the instrument list for a specific domain."""
    return [i for i in MARKET_INSTRUMENT_DEFINITIONS if domain_id in i["domain_ids"]]

def get_all_unique_symbols() -> Dict[str, List[str]]:
    """Returns a flat dictionary of all symbols by type (etf, fx, crypto, etc.)."""
    all_symbols = {
        "equity": set(),
        "fx": set(),
        "crypto": set(),
        "commodity": set(),
        "index": set()
    }
    
    for i in MARKET_INSTRUMENT_DEFINITIONS:
        if i["asset_class"] == "equity": all_symbols["equity"].add(i["symbol"])
        elif i["asset_class"] == "fx": all_symbols["fx"].add(i["symbol"])
        elif i["asset_class"] == "crypto": all_symbols["crypto"].add(i["symbol"])
        elif i["asset_class"] == "commodity": all_symbols["commodity"].add(i["symbol"])
        elif i["asset_class"] == "index": all_symbols["index"].add(i["symbol"])

    return {k: sorted(list(v)) for k, v in all_symbols.items()}
