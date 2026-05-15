"""
FRED Series Catalog.

Centralizes the series IDs and metadata for economic indicators used
in Pro reports and quantitative analysis.
"""

from typing import Any, Dict, List

FRED_SERIES_CATALOG = {
    "monetary_policy": [
        {
            "series_id": "FEDFUNDS",
            "name": "Effective Federal Funds Rate",
            "unit": "percent",
            "frequency_hint": "monthly",
            "pro_use": "policy_rate_context"
        },
        {
            "series_id": "DGS10",
            "name": "10-Year Treasury Constant Maturity Rate",
            "unit": "percent",
            "frequency_hint": "daily",
            "pro_use": "long_rate_context"
        }
    ],
    "inflation": [
        {
            "series_id": "CPIAUCSL",
            "name": "Consumer Price Index for All Urban Consumers",
            "unit": "index",
            "frequency_hint": "monthly",
            "pro_use": "inflation_context"
        }
    ],
    "energy": [
        {
            "series_id": "DCOILWTICO",
            "name": "WTI Crude Oil Price",
            "unit": "usd_per_barrel",
            "frequency_hint": "daily",
            "pro_use": "energy_price_context"
        },
        {
            "series_id": "GASREGW",
            "name": "U.S. City Average Retail Gasoline Price",
            "unit": "usd_per_gallon",
            "frequency_hint": "weekly",
            "pro_use": "gasoline_price_context"
        }
    ],
    "currency": [
        {
            "series_id": "DTWEXBGS",
            "name": "Nominal Broad U.S. Dollar Index",
            "unit": "index",
            "frequency_hint": "daily",
            "pro_use": "usd_strength_context"
        }
    ],
    "defense": [
        {
            "series_id": "FDEFX",
            "name": "Real National Defense Consumption Expenditures and Gross Investment",
            "unit": "billions_of_chained_2017_usd",
            "frequency_hint": "quarterly",
            "pro_use": "defense_spending_context"
        }
    ],
    "industrial": [
        {
            "series_id": "IPB53122S",
            "name": "Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component",
            "unit": "index",
            "frequency_hint": "monthly",
            "pro_use": "semi_production_context"
        },
        {
            "series_id": "IPI",
            "name": "Industrial Production Index",
            "unit": "index",
            "frequency_hint": "monthly",
            "pro_use": "industrial_output_context"
        }
    ],
    "monetary": [
        {
            "series_id": "M2SL",
            "name": "M2 Money Stock",
            "unit": "billions_of_dollars",
            "frequency_hint": "monthly",
            "pro_use": "liquidity_context"
        }
    ]
}

def get_all_fred_series() -> List[Dict[str, Any]]:
    """Return a flat list of all series in the catalog with their category."""
    all_series = []
    for category, series_list in FRED_SERIES_CATALOG.items():
        for series in series_list:
            entry = series.copy()
            entry["category"] = category
            all_series.append(entry)
    return all_series

def get_fred_series_by_category(category: str) -> List[Dict[str, Any]]:
    """Return all series belonging to a specific category."""
    return FRED_SERIES_CATALOG.get(category, [])

def get_fred_series_ids() -> List[str]:
    """Return a flat list of all series IDs in the catalog."""
    return [s["series_id"] for s in get_all_fred_series()]
