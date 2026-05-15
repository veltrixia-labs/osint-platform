"""
World Bank Indicator Catalog.

Centralizes IDs and metadata for international economic and demographic
indicators used in global macro analysis.
"""

from typing import Any, Dict, List

WORLDBANK_INDICATOR_CATALOG = {
    "growth": [
        {
            "indicator_id": "NY.GDP.MKTP.CD",
            "name": "GDP (current US$)",
            "pro_use": "global_economic_scale"
        },
        {
            "indicator_id": "NY.GDP.MKTP.KD.ZG",
            "name": "GDP growth (annual %)",
            "pro_use": "macro_growth_comparison"
        }
    ],
    "stability": [
        {
            "indicator_id": "FP.CPI.TOTL.ZG",
            "name": "Inflation, consumer prices (annual %)",
            "pro_use": "global_inflation_context"
        }
    ],
    "trade": [
        {
            "indicator_id": "NE.TRD.GNFS.ZS",
            "name": "Trade (% of GDP)",
            "pro_use": "trade_openness_exposure"
        },
        {
            "indicator_id": "NE.EXP.GNFS.ZS",
            "name": "Exports of goods and services (% of GDP)",
            "pro_use": "export_dependency"
        },
        {
            "indicator_id": "NE.IMP.GNFS.ZS",
            "name": "Imports of goods and services (% of GDP)",
            "pro_use": "import_dependency"
        }
    ],
    "demographics": [
        {
            "indicator_id": "SP.POP.TOTL",
            "name": "Population, total",
            "pro_use": "market_size_scaling"
        }
    ]
}

def get_all_indicators() -> List[Dict[str, Any]]:
    """Return a flat list of all indicators in the catalog with their category."""
    all_inds = []
    for category, ind_list in WORLDBANK_INDICATOR_CATALOG.items():
        for ind in ind_list:
            entry = ind.copy()
            entry["category"] = category
            all_inds.append(entry)
    return all_inds

def get_indicator_ids() -> List[str]:
    """Return a flat list of all indicator IDs in the catalog."""
    return [i["indicator_id"] for i in get_all_indicators()]
