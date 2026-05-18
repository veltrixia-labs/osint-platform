"""
EIA API v2 petroleum series catalog.

User-facing routes (legacy names in docs) map to current API paths:
  petroleum/stoc/wst  -> petroleum/stoc/wstk  (weekly stocks)
  petroleum/pnp/wiu   -> petroleum/pnp/wiup   (refiner inputs / utilization)
  petroleum/move/wkly -> seriesid PET.WCRFPUS2.W (field production; not on move/wkly facet)
"""

from typing import Any, Dict, List

EIA_SERIES_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "crude_stocks": [
        {
            "series_id": "WCESTUS1",
            "name": "U.S. Ending Stocks excluding SPR of Crude Oil",
            "api_route": "petroleum/stoc/wstk",
            "legacy_route": "petroleum/stoc/wst",
            "fetch_via": "route",
            "facets": {"series": ["WCESTUS1"], "duoarea": ["NUS"]},
            "unit": "MBBL",
            "frequency_hint": "weekly",
            "category": "crude_stocks",
            "pro_use": "crude_inventory_signal",
            "geography": "US",
        }
    ],
    "refinery_utilization": [
        {
            "series_id": "WPULEUS3",
            "name": "U.S. Percent Utilization of Refinery Operable Capacity",
            "api_route": "petroleum/pnp/wiup",
            "legacy_route": "petroleum/pnp/wiu",
            "fetch_via": "route",
            "facets": {"series": ["WPULEUS3"], "duoarea": ["NUS"]},
            "unit": "percent",
            "frequency_hint": "weekly",
            "category": "refinery_utilization",
            "pro_use": "refinery_capacity_utilization",
            "geography": "US",
        }
    ],
    "crude_production": [
        {
            "series_id": "WCRFPUS2",
            "name": "U.S. Field Production of Crude Oil",
            "api_route": "petroleum/move/wkly",
            "legacy_route": "petroleum/move/wkly",
            "fetch_via": "seriesid",
            "v1_series_id": "PET.WCRFPUS2.W",
            "facets": {},
            "unit": "MBBL/D",
            "frequency_hint": "weekly",
            "category": "crude_production",
            "pro_use": "domestic_crude_supply",
            "geography": "US",
        }
    ],
}


def get_all_eia_series() -> List[Dict[str, Any]]:
    """Flat list of all catalogued EIA series with category label."""
    all_series: List[Dict[str, Any]] = []
    for category, entries in EIA_SERIES_CATALOG.items():
        for entry in entries:
            row = entry.copy()
            row["category"] = category
            all_series.append(row)
    return all_series
