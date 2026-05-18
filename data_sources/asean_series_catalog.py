"""
ASEANstats indicator catalog.

API: https://data.aseanstats.org/api/indicator/{code}
"""

from typing import Any, Dict, List

ASEAN_SERIES_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "fdi": [
        {
            "indicator_code": "FDI.AMS.TOT.INF",
            "series_id": "FDI.AMS.TOT.INF",
            "name": "ASEAN Total FDI Inflows",
            "unit": "million USD",
            "frequency_hint": "annual",
            "category": "fdi",
            "pro_use": "asean_investment_flow",
            "geography": "ASEAN",
            "aggregate_host_code": "ASEAN",
        }
    ],
    "trade_goods": [
        {
            "indicator_code": "IMTS.Annually",
            "series_id": "IMTS.Annually",
            "name": "ASEAN Trade in Goods (annual, aggregate)",
            "unit": "million USD",
            "frequency_hint": "annual",
            "category": "trade_goods",
            "pro_use": "asean_trade_goods",
            "geography": "ASEAN",
            "aggregate_host_code": "ASEAN",
            "optional": True,
        }
    ],
}


def get_all_asean_series() -> List[Dict[str, Any]]:
    all_series: List[Dict[str, Any]] = []
    for category, entries in ASEAN_SERIES_CATALOG.items():
        for entry in entries:
            row = entry.copy()
            row["category"] = category
            all_series.append(row)
    return all_series
