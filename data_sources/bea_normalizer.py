"""
BEA API response normalizer.

Converts raw BEA API JSON responses into flat, DB-ready row dicts.
"""

from typing import Any, Dict, List, Optional


def _parse_data_value(raw: str) -> Optional[float]:
    """Convert DataValue string to float; return None if not parseable."""
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def _build_notes_map(notes: List[Dict[str, str]]) -> Dict[str, str]:
    """
    Convert the Notes array into a { NoteRef: NoteText } lookup dict.

    Example input:
        [{"NoteRef": "1", "NoteText": "Value Added by Industry ..."}]
    """
    return {n["NoteRef"]: n["NoteText"] for n in notes if "NoteRef" in n}


def _resolve_note_text(note_ref: str, notes_map: Dict[str, str]) -> str:
    """
    Resolve note text for a given NoteRef.

    Some rows have composite refs like "1;1.1.A".
    We join all matching texts with " | ".
    """
    if not note_ref:
        return ""
    refs = [r.strip() for r in note_ref.split(";")]
    texts = [notes_map[r] for r in refs if r in notes_map]
    return " | ".join(texts)


def _get_industry_description(row: Dict[str, Any]) -> str:
    """
    Extract industry description, handling both the correct key
    (IndustryDescription) and the BEA API typo (IndustrYDescription).
    """
    return row.get("IndustryDescription") or row.get("IndustrYDescription") or ""


def normalize_gdp_by_industry(raw_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalize a raw BEA GDPbyIndustry response into flat row dicts.

    Parameters
    ----------
    raw_json : dict
        The full JSON response from the BEA API (top-level key: "BEAAPI").

    Returns
    -------
    list[dict]
        A list of normalized row dicts ready for downstream storage.
    """
    beaapi = raw_json.get("BEAAPI", {})
    results = beaapi.get("Results", [])

    # Results can be a list or a dict depending on the endpoint
    if isinstance(results, list):
        if len(results) == 0:
            return []
        result_block = results[0]
    elif isinstance(results, dict):
        result_block = results
    else:
        return []

    # Extract metadata
    statistic = result_block.get("Statistic", "")
    utc_production_time = result_block.get("UTCProductionTime", "")

    # Build notes lookup
    notes_raw = result_block.get("Notes", [])
    notes_map = _build_notes_map(notes_raw)

    # Process each data row
    data_rows = result_block.get("Data", [])
    normalized: List[Dict[str, Any]] = []

    for row in data_rows:
        note_ref = row.get("NoteRef", "")
        normalized.append({
            "dataset_name": "GDPbyIndustry",
            "table_id": row.get("TableID", ""),
            "frequency": row.get("Frequency", ""),
            "year": row.get("Year", ""),
            "quarter": row.get("Quarter", ""),
            "industry": row.get("Industry", ""),
            "industry_description": _get_industry_description(row),
            "data_value": _parse_data_value(row.get("DataValue")),
            "note_ref": note_ref,
            "note_text": _resolve_note_text(note_ref, notes_map),
            "statistic": statistic,
            "utc_production_time": utc_production_time,
        })

    return normalized
