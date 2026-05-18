"""
ECB Statistical Data Warehouse series catalog.

series_key is the SDMX series path appended to /service/data/
series_id uses dots instead of slashes for DB storage and domain config.
"""

from typing import Any, Dict, List


def series_key_to_id(series_key: str) -> str:
    return series_key.strip("/").replace("/", ".")


ECB_SERIES_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "policy_rate": [
        {
            "series_key": "FM/D.U2.EUR.4F.KR.MRR_FAC.LEV",
            "series_id": series_key_to_id("FM/D.U2.EUR.4F.KR.MRR_FAC.LEV"),
            "name": "ECB Main Refinancing Operations Rate",
            "unit": "percent",
            "frequency_hint": "daily",
            "category": "policy_rate",
            "pro_use": "ecb_policy_rate",
            "geography": "EA",
        }
    ],
    "fx": [
        {
            "series_key": "EXR/D.USD.EUR.SP00.A",
            "series_id": series_key_to_id("EXR/D.USD.EUR.SP00.A"),
            "name": "EUR/USD Reference Exchange Rate",
            "unit": "USD/EUR",
            "frequency_hint": "daily",
            "category": "fx",
            "pro_use": "eur_usd_fx",
            "geography": "EA",
        }
    ],
    "inflation": [
        {
            "series_key": "ICP/M.U2.N.000000.4.ANR",
            "series_id": series_key_to_id("ICP/M.U2.N.000000.4.ANR"),
            "name": "Euro Area HICP (Annual Rate of Change)",
            "unit": "percent",
            "frequency_hint": "monthly",
            "category": "inflation",
            "pro_use": "euroarea_hicp",
            "geography": "EA",
        }
    ],
}


def get_all_ecb_series() -> List[Dict[str, Any]]:
    """Flat list of all catalogued ECB series with category label."""
    all_series: List[Dict[str, Any]] = []
    for category, entries in ECB_SERIES_CATALOG.items():
        for entry in entries:
            row = entry.copy()
            row["category"] = category
            all_series.append(row)
    return all_series
