"""
BCB SGS API client (Banco Central do Brasil).

No API key required.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

BCB_SGS_BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs"


class BCBClient(BaseAPIClient):
    def __init__(self):
        super().__init__(
            source_name="BCB",
            base_url=BCB_SGS_BASE,
            api_key_env=None,
            api_key_required=False,
            timeout=60,
        )

    def get_series(
        self,
        sgs_id: int,
        *,
        data_inicial: Optional[str] = None,
        data_final: Optional[str] = None,
        ultimos: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        url = f"{BCB_SGS_BASE}.{sgs_id}/dados"
        params: Dict[str, Any] = {"formato": "json"}
        if ultimos is not None:
            params["ultimos"] = ultimos
        if data_inicial:
            params["dataInicial"] = data_inicial
        if data_final:
            params["dataFinal"] = data_final
        try:
            payload = self.get_json(url, params=params)
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict) and payload.get("error"):
                logger.error("BCB error for series %s: %s", sgs_id, payload)
            return []
        except Exception as exc:
            logger.error("BCB fetch failed for series %s: %s", sgs_id, exc)
            return []

    def fetch_series_observations(
        self,
        sgs_id: int,
        *,
        lookback_days: int = 400,
        max_observations: int = 60,
    ) -> List[Dict[str, Any]]:
        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        rows = self.get_series(
            sgs_id,
            data_inicial=start.strftime("%d/%m/%Y"),
            data_final=end.strftime("%d/%m/%Y"),
        )
        parsed = [row for row in (normalize_bcb_row(r) for r in rows) if row]
        parsed.sort(key=lambda r: r["date"], reverse=True)
        return parsed[:max_observations]


def parse_bcb_date(date_str: str) -> Optional[date]:
    text = (date_str or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_bcb_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if text in ("", "-", "ND"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_bcb_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    dt = parse_bcb_date(str(row.get("data", "")))
    val = parse_bcb_value(row.get("valor"))
    if dt is None or val is None:
        return None
    return {
        "date": dt.isoformat(),
        "value": val,
        "period_label": str(row.get("data", "")),
        "raw": row,
    }
