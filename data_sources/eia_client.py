"""
EIA API v2 Client (U.S. Energy Information Administration).

Fetches weekly petroleum statistics via route-based queries and legacy series IDs.
Requires EIA_API_KEY from https://www.eia.gov/opendata/
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from data_sources.base_client import BaseAPIClient, redact_credentials

logger = logging.getLogger(__name__)

EIA_API_BASE = "https://api.eia.gov/v2"


class EIAClient(BaseAPIClient):
    def _get_json_params(
        self, url: str, params: List[Tuple[str, Any]]
    ) -> Dict[str, Any]:
        """GET with repeated query keys (facets) — dict params cannot represent these."""
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            source_name="EIA",
            base_url=EIA_API_BASE,
            api_key_env="EIA_API_KEY",
            api_key_required=True,
        )
        if api_key:
            self.api_key = api_key

    def get_route_data(
        self,
        api_route: str,
        *,
        frequency: str = "weekly",
        facets: Optional[Dict[str, List[str]]] = None,
        length: int = 52,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """GET /v2/{route}/data with optional facets."""
        route = api_route.strip("/")
        url = f"{EIA_API_BASE}/{route}/data"
        params: List[Tuple[str, Any]] = [
            ("api_key", self.api_key),
            ("frequency", frequency),
            ("data[0]", "value"),
            ("length", length),
            ("offset", offset),
            ("sort[0][column]", "period"),
            ("sort[0][direction]", "desc"),
        ]
        for facet_name, values in (facets or {}).items():
            for value in values:
                params.append((f"facets[{facet_name}][]", value))
        try:
            return self._get_json_params(url, params)
        except Exception as exc:
            # api_key is a query parameter; _get_json_params raises straight from
            # requests, so the message carries the full URL.
            safe = redact_credentials(exc)
            logger.error("EIA route fetch failed for %s: %s", api_route, safe)
            return {"error": safe, "api_route": api_route}

    def get_seriesid_data(
        self,
        v1_series_id: str,
        *,
        length: int = 52,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """GET /v2/seriesid/{legacy_series_id} for series not exposed on a route facet."""
        url = f"{EIA_API_BASE}/seriesid/{v1_series_id}"
        params = {
            "api_key": self.api_key,
            "length": length,
            "offset": offset,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
        }
        try:
            return self.get_json(url, params=params)
        except Exception as exc:
            safe = redact_credentials(exc)
            logger.error("EIA seriesid fetch failed for %s: %s", v1_series_id, safe)
            return {"error": safe, "v1_series_id": v1_series_id}

    def fetch_catalog_observations(
        self,
        *,
        api_route: Optional[str] = None,
        legacy_route: Optional[str] = None,
        fetch_via: str = "route",
        facets: Optional[Dict[str, List[str]]] = None,
        v1_series_id: Optional[str] = None,
        frequency: str = "weekly",
        max_observations: int = 52,
    ) -> List[Dict[str, Any]]:
        """
        Fetch and normalize observations for one catalog entry.
        """
        if fetch_via == "seriesid":
            if not v1_series_id:
                return []
            raw = self.get_seriesid_data(v1_series_id, length=max_observations)
        else:
            if not api_route:
                return []
            raw = self.get_route_data(
                api_route,
                frequency=frequency,
                facets=facets,
                length=max_observations,
            )

        if raw.get("error"):
            return []

        rows = raw.get("response", {}).get("data", [])
        if not isinstance(rows, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            parsed = normalize_eia_row(row, api_route=api_route or legacy_route)
            if parsed:
                normalized.append(parsed)

        normalized.sort(key=lambda r: r["date"], reverse=True)
        return normalized[:max_observations]


def parse_eia_period(period: Any) -> Optional[date]:
    """Parse EIA period (typically YYYY-MM-DD) to date."""
    if period is None:
        return None
    text = str(period).strip()
    if not text:
        return None
    for fmt, size in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            return datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def parse_eia_value(value: Any) -> Optional[float]:
    """Parse EIA value (API returns strings since v2.1.6)."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in ("", ".", "-", "NA", "null"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_eia_row(row: Dict[str, Any], api_route: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Normalize one EIA data row to storage format."""
    dt = parse_eia_period(row.get("period"))
    val = parse_eia_value(row.get("value"))
    if dt is None or val is None:
        return None
    return {
        "date": dt.isoformat(),
        "value": val,
        "period_label": str(row.get("period", "")),
        "series": row.get("series"),
        "units": row.get("units"),
        "api_route": api_route,
        "raw": row,
    }
