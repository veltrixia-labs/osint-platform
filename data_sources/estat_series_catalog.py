"""
e-Stat (Japanese government statistics) series catalog.

stats_data_id values map to the e-Stat API statsDataId parameter.
series_id is stored in external_data_series.series_id (same as stats_data_id).
"""

from typing import Any, Dict, List

ESTAT_SERIES_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "industrial_production": [
        {
            "stats_data_id": "0004052177",
            "series_id": "0004052177",
            "name": "Japan IIP — production, by industry, monthly, seasonally adjusted (2020=100)",
            "unit": "index",
            "frequency_hint": "monthly",
            "category": "industrial_production",
            "pro_use": "japan_manufacturing_cycle",
            "geography": "JP",
            "narrowing": {"cdCat01": "0001000"},
        }
    ],
    "consumer_prices": [
        {
            "stats_data_id": "0003427113",
            "series_id": "0003427113",
            "name": "Japan Consumer Price Index (2020 base)",
            "unit": "index",
            "frequency_hint": "monthly",
            "category": "consumer_prices",
            "pro_use": "japan_inflation_context",
            "geography": "JP",
            "narrowing": {"cdTab": "1", "cdCat01": "0001", "cdArea": "00000"},
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
