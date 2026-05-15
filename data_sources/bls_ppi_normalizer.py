"""
BLS PPI Normalizer.

Converts raw BLS Public Data API v2 responses into a normalized row format
suitable for time-series analysis and DB storage.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

PPI_SERIES_NAMES = {
    "WPUFD4": "PPI Final demand",
    "WPUFD49104": "Final demand goods",
    "WPUFD49207": "Final demand services",
    "WPU057": "Fuels and related products and power",
    "WPU101": "Iron and steel",
    "WPU081": "Lumber and wood products",
    "WPU114": "Machinery and equipment",
    "WPU117": "Electronic components and accessories",
}

def normalize_bls_ppi_data(raw_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalizes BLS API response into a flat list of observation dicts.
    
    Args:
        raw_json: The raw JSON response from BLS Public Data API v2.
        
    Returns:
        List of normalized observation dictionaries.
    """
    normalized_rows = []
    
    results = raw_json.get("Results", {})
    series_list = results.get("series", [])
    
    for series in series_list:
        series_id = series.get("seriesID")
        series_name = PPI_SERIES_NAMES.get(series_id, "Unknown PPI Series")
        data_points = series.get("data", [])
        
        # Sort data points by year and period ascending for proper latest detection
        # BLS usually returns descending (latest first)
        data_points.sort(key=lambda x: (x.get("year"), x.get("period")), reverse=True)
        
        for i, dp in enumerate(data_points):
            year_str = dp.get("year")
            period = dp.get("period") # e.g. "M12"
            
            # Skip annual averages (M13) if only monthly data is desired
            if period == "M13":
                continue
                
            period_name = dp.get("periodName")
            value_str = dp.get("value")
            
            # Convert year and value
            try:
                year = int(year_str)
            except (ValueError, TypeError):
                year = 0
                
            try:
                value = float(value_str)
            except (ValueError, TypeError):
                value = None
            
            # Format date (YYYY-MM)
            # period M01 -> 01
            month_part = period[1:] if len(period) == 3 else "00"
            date_str = f"{year}-{month_part}"
            
            row = {
                "source": "BLS",
                "dataset_name": "PPI",
                "series_id": series_id,
                "series_name": series_name,
                "year": year,
                "period": period,
                "period_name": period_name,
                "date": date_str,
                "value": value,
                "footnotes": dp.get("footnotes", []),
                "latest": (i == 0) # Assumes descending sort
            }
            normalized_rows.append(row)
            
    return normalized_rows
