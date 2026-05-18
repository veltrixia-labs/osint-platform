"""
BCB (Banco Central do Brasil) SGS series catalog.

API: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{id}/dados?formato=json
Dates use dd/MM/yyyy (dataInicial / dataFinal).
"""

from typing import Any, Dict, List

BCB_SERIES_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "policy_rate": [
        {
            "sgs_id": 11,
            "series_id": "BCB.11",
            "name": "Brazil Selic (daily)",
            "unit": "percent_per_day",
            "frequency_hint": "daily",
            "category": "policy_rate",
            "pro_use": "brazil_policy_rate",
            "geography": "BR",
        }
    ],
    "fx": [
        {
            "sgs_id": 1,
            "series_id": "BCB.1",
            "name": "Brazil USD/BRL PTAX",
            "unit": "BRL per USD",
            "frequency_hint": "daily",
            "category": "fx",
            "pro_use": "brazil_fx_em",
            "geography": "BR",
        }
    ],
    "inflation": [
        {
            "sgs_id": 433,
            "series_id": "BCB.433",
            "name": "Brazil IPCA (monthly change)",
            "unit": "percent",
            "frequency_hint": "monthly",
            "category": "inflation",
            "pro_use": "brazil_inflation",
            "geography": "BR",
        }
    ],
}


def get_all_bcb_series() -> List[Dict[str, Any]]:
    all_series: List[Dict[str, Any]] = []
    for category, entries in BCB_SERIES_CATALOG.items():
        for entry in entries:
            row = entry.copy()
            row["category"] = category
            all_series.append(row)
    return all_series
