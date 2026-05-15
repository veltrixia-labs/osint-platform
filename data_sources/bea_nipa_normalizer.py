"""
BEA NIPA response normalizer.

Converts raw BEA NIPA JSON responses into flat, DB-ready row dicts.
Handles comma-separated numerical strings and NIPA-specific metadata.
"""

import re
from typing import Any, Dict, List, Optional


def _parse_nipa_value(raw: Any) -> Optional[float]:
    """
    Convert NIPA DataValue string to float.
    Handles commas (e.g., "20,656,516") and special codes like (D), ..., or empty strings.
    """
    if raw is None:
        return None
    
    s = str(raw).strip()
    
    # Check for non-numeric BEA codes
    # (D) = Suppressed to avoid disclosure
    # (...) = Not available
    if not s or s == "(D)" or s == "..." or s == "(L)":
        return None
    
    # Remove commas
    s = s.replace(",", "")
    
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_int(raw: Any) -> Optional[int]:
    """Safely convert to int."""
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def normalize_nipa_data(raw_json: Dict[str, Any], frequency: str = "A") -> List[Dict[str, Any]]:
    """
    Normalize a raw BEA NIPA response into flat row dicts.

    Parameters
    ----------
    raw_json : dict
        The full JSON response from the BEA API (top-level key: "BEAAPI").
    frequency : str
        Frequency to assign (e.g. "A" for Annual).

    Returns
    -------
    list[dict]
        A list of normalized row dicts.
    """
    beaapi = raw_json.get("BEAAPI", {})
    results = beaapi.get("Results", {})

    # NIPA Results is usually a dict, but handling list for robustness
    if isinstance(results, list):
        if len(results) == 0:
            return []
        result_block = results[0]
    elif isinstance(results, dict):
        result_block = results
    else:
        return []

    # Extract metadata
    statistic = result_block.get("Statistic", "NIPA Table")
    utc_production_time = result_block.get("UTCProductionTime", "")

    # Process each data row
    data_rows = result_block.get("Data", [])
    normalized: List[Dict[str, Any]] = []

    for row in data_rows:
        normalized.append({
            "dataset_name": "NIPA",
            "table_name": row.get("TableName", ""),
            "series_code": row.get("SeriesCode", ""),
            "line_number": row.get("LineNumber", ""),
            "line_description": row.get("LineDescription", ""),
            "time_period": row.get("TimePeriod", ""),
            "frequency": frequency,
            "metric_name": row.get("METRIC_NAME", ""),
            "cl_unit": row.get("CL_UNIT", ""),
            "unit_mult": _parse_int(row.get("UNIT_MULT")),
            "data_value": _parse_nipa_value(row.get("DataValue")),
            "note_ref": row.get("NoteRef", ""),
            "statistic": statistic,
            "utc_production_time": utc_production_time,
        })

    return normalized
