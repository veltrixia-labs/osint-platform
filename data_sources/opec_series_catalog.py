"""
OPEC-related energy indicators.

Official OPEC portal has no stable public JSON API; production series are
sourced from KAPSARC Open Data (world-oil-production, OPEC aggregate).
"""

from typing import Any, Dict, List

OPEC_SERIES_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "crude_production": [
        {
            "series_id": "OPEC.CRUDE_PRODUCTION",
            "name": "OPEC Crude Oil Production",
            "kapsarc_dataset": "world-oil-production",
            "kapsarc_filter": 'producers="OPEC"',
            "unit": "mb/d",
            "frequency_hint": "annual",
            "category": "crude_production",
            "pro_use": "opec_supply_aggregate",
            "geography": "OPEC",
        }
    ],
    "world_production": [
        {
            "series_id": "WORLD.CRUDE_PRODUCTION",
            "name": "World Crude Oil Production",
            "kapsarc_dataset": "world-oil-production",
            "kapsarc_filter": 'producers="World"',
            "unit": "mb/d",
            "frequency_hint": "annual",
            "category": "world_production",
            "pro_use": "global_supply_context",
            "geography": "GLOBAL",
        }
    ],
}


def get_all_opec_series() -> List[Dict[str, Any]]:
    all_series: List[Dict[str, Any]] = []
    for category, entries in OPEC_SERIES_CATALOG.items():
        for entry in entries:
            row = entry.copy()
            row["category"] = category
            all_series.append(row)
    return all_series
