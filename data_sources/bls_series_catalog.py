"""
BLS Series Catalog.

Centralizes the series IDs and metadata for economic indicators (PPI, etc.)
used in Pro reports and price pressure analysis.
"""

from typing import Any, Dict, List

BLS_SERIES_CATALOG = {
    "ppi_headline": [
        {
            "series_id": "WPUFD4",
            "name": "PPI Final Demand",
            "unit": "index",
            "pro_use": "headline_producer_price_pressure"
        }
    ],
    "energy_price_pressure": [
        {
            "series_id": "WPU05",
            "name": "PPI Fuels and Related Products and Power",
            "unit": "index",
            "pro_use": "energy_cost_pressure"
        },
        {
            "series_id": "WPU051",
            "name": "PPI Crude Petroleum",
            "unit": "index",
            "pro_use": "crude_petroleum_cost_pressure"
        }
    ],
    "industrial_materials": [
        {
            "series_id": "WPU101",
            "name": "PPI Metals and Metal Products",
            "unit": "index",
            "pro_use": "industrial_input_cost_pressure"
        }
    ],
    "specialized_manufacturing": [
        {
            "series_id": "PCU334413334413",
            "name": "PPI Semiconductors and Related Device Manufacturing",
            "unit": "index",
            "pro_use": "semi_manufacturing_cost_pressure"
        },
        {
            "series_id": "PCU336411336411",
            "name": "PPI Aircraft Manufacturing",
            "unit": "index",
            "pro_use": "aerospace_manufacturing_cost_pressure"
        }
    ]
}

def get_all_bls_series() -> List[Dict[str, Any]]:
    """Return a flat list of all series in the catalog with their category."""
    all_series = []
    for category, series_list in BLS_SERIES_CATALOG.items():
        for series in series_list:
            entry = series.copy()
            entry["category"] = category
            all_series.append(entry)
    return all_series

def get_bls_series_by_category(category: str) -> List[Dict[str, Any]]:
    """Return all series belonging to a specific category."""
    return BLS_SERIES_CATALOG.get(category, [])

def get_bls_series_ids() -> List[str]:
    """Return a flat list of all series IDs in the catalog."""
    return [s["series_id"] for s in get_all_bls_series()]
