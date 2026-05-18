"""
OPEC energy statistics client.

Primary source: KAPSARC Open Data API (OPEC aggregates from world-oil-production).
Official OPEC publications do not expose a stable machine-readable API.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

KAPSARC_API_BASE = "https://datasource.kapsarc.org/api/explore/v2.1/catalog/datasets"
OPEC_PORTAL_BASE = "https://www.opec.org"


class OPECClient(BaseAPIClient):
    def __init__(self):
        super().__init__(
            source_name="OPEC",
            base_url=KAPSARC_API_BASE,
            api_key_env=None,
            api_key_required=False,
            timeout=60,
        )
        self.session.headers.setdefault(
            "User-Agent",
            os.getenv("OPEC_HTTP_USER_AGENT", "VELTRIXIA-OSINT/1.0"),
        )

    def get_kapsarc_records(
        self,
        dataset: str,
        *,
        where: Optional[str] = None,
        limit: int = 60,
        order_by: str = "time_period desc",
    ) -> List[Dict[str, Any]]:
        url = f"{KAPSARC_API_BASE}/{dataset}/records"
        params: Dict[str, Any] = {"limit": limit, "order_by": order_by}
        if where:
            params["where"] = where
        try:
            payload = self.get_json(url, params=params)
            results = payload.get("results", [])
            return results if isinstance(results, list) else []
        except Exception as exc:
            logger.error("KAPSARC fetch failed for %s: %s", dataset, exc)
            return []

    def fetch_catalog_observations(
        self,
        *,
        kapsarc_dataset: str,
        kapsarc_filter: Optional[str] = None,
        max_observations: int = 60,
    ) -> List[Dict[str, Any]]:
        rows = self.get_kapsarc_records(
            kapsarc_dataset,
            where=kapsarc_filter,
            limit=max_observations,
        )
        parsed = [row for row in (normalize_kapsarc_row(r) for r in rows) if row]
        parsed.sort(key=lambda r: r["date"], reverse=True)
        return parsed[:max_observations]


def normalize_kapsarc_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    period = row.get("time_period") or row.get("date_object")
    dt = parse_opec_period(period)
    val = parse_opec_value(row.get("value"))
    if dt is None or val is None:
        return None
    return {
        "date": dt.isoformat(),
        "value": val,
        "period_label": str(period),
        "producers": row.get("producers"),
        "raw": row,
    }


def parse_opec_period(period: Any) -> Optional[date]:
    if period is None:
        return None
    text = str(period).strip()
    if not text:
        return None
    if len(text) >= 10 and "-" in text:
        try:
            return datetime.fromisoformat(text[:10]).date()
        except ValueError:
            pass
    if text.isdigit() and len(text) == 4:
        return date(int(text), 1, 1)
    return None


def parse_opec_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
