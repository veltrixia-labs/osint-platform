"""
e-Stat (Japanese government statistics) series catalog.

stats_data_id values map to the e-Stat API statsDataId parameter.
series_id is stored in external_data_series.series_id (same as stats_data_id).
"""

from typing import Any, Dict, List

ESTAT_SERIES_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "industrial_production": [
        {
            "stats_data_id": "0003410537",
            "series_id": "0003410537",
            "name": "Japan Index of Industrial Production (IIP)",
            "unit": "index",
            "frequency_hint": "monthly",
            "category": "industrial_production",
            "pro_use": "japan_manufacturing_cycle",
            "geography": "JP",
        }
    ],
    "consumer_prices": [
        {
            "stats_data_id": "0003423164",
            "series_id": "0003423164",
            "name": "Japan Consumer Price Index (CPI)",
            "unit": "index",
            "frequency_hint": "monthly",
            "category": "consumer_prices",
            "pro_use": "japan_inflation_context",
            "geography": "JP",
        }
    ],
}


def get_all_estat_series() -> List[Dict[str, Any]]:
    """Flat list of all catalogued e-Stat series with category label."""
    all_series: List[Dict[str, Any]] = []
    for category, entries in ESTAT_SERIES_CATALOG.items():
        for entry in entries:
            row = entry.copy()
            row["category"] = category
            all_series.append(row)
    return all_series
