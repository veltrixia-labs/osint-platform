"""
External Data Source Registry.

Centralizes metadata about all integrated external data sources, 
their categories, authentication requirements, and target storage types.
"""

EXTERNAL_DATA_SOURCES = {
    "fred": {
        "name": "FRED",
        "category": "macro_financial_timeseries",
        "api_key_env": "FRED_API_KEY",
        "storage_type": "generic_timeseries",
    },
    "bls": {
        "name": "BLS",
        "category": "price_pressure",
        "api_key_env": "BLS_API_KEY",
        "storage_type": "generic_timeseries",
    },
    "worldbank": {
        "name": "World Bank",
        "category": "global_macro",
        "api_key_env": None,
        "storage_type": "generic_timeseries",
    },
    "comtrade": {
        "name": "UN Comtrade",
        "category": "trade_flow",
        "api_key_env": "COMTRADE_API_KEY",
        "storage_type": "trade_flow",
    },
    "bea": {
        "name": "BEA",
        "category": "industry_structure",
        "api_key_env": "BEA_API_KEY",
        "storage_type": "industry_stats",
    },
    "census": {
        "name": "Census",
        "category": "geo_business_stats",
        "api_key_env": "CENSUS_API_KEY",
        "storage_type": "industry_stats",
    },
    "estat": {
        "name": "e-Stat",
        "category": "japan_macro",
        "api_key_env": "ESTAT_APP_ID",
        "storage_type": "generic_timeseries",
    },
    "eia": {
        "name": "EIA",
        "category": "energy_macro",
        "api_key_env": "EIA_API_KEY",
        "storage_type": "generic_timeseries",
    },
}

def get_source_config(source_id: str) -> dict:
    """Helper to get a specific source's configuration."""
    return EXTERNAL_DATA_SOURCES.get(source_id, {})
