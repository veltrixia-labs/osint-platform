"""
UN Comtrade Commodity Catalog.

Centralizes HS codes and metadata for critical commodities monitored
for supply chain and trade dependency analysis.
"""

from typing import Any, Dict, List

COMTRADE_COMMODITY_CATALOG = {
    "energy": [
        {
            "commodity_code": "2709",
            "name": "Crude petroleum oils",
            "pro_use": "crude_oil_trade_dependency"
        },
        {
            "commodity_code": "2711",
            "name": "Petroleum gases and other gaseous hydrocarbons",
            "pro_use": "lng_gas_trade_dependency"
        }
    ],
    "semiconductors": [
        {
            "commodity_code": "8542",
            "name": "Electronic integrated circuits",
            "pro_use": "semiconductor_trade_dependency"
        }
    ],
    "critical_minerals": [
        {
            "commodity_code": "2805",
            "name": "Alkali or rare-earth metals",
            "pro_use": "critical_material_trade_dependency"
        }
    ]
}

def get_all_commodities() -> List[Dict[str, Any]]:
    """Return a flat list of all commodities in the catalog with their category."""
    all_cmds = []
    for category, cmd_list in COMTRADE_COMMODITY_CATALOG.items():
        for cmd in cmd_list:
            entry = cmd.copy()
            entry["category"] = category
            all_cmds.append(entry)
    return all_cmds

def get_commodity_ids() -> List[str]:
    """Return a flat list of all commodity codes in the catalog."""
    return [c["commodity_code"] for c in get_all_commodities()]
