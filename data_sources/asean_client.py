"""
ASEANstats API client.

No API key required. Some large indicators may return errors; callers should
tolerate empty results for optional series.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional

from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

ASEAN_API_BASE = "https://data.aseanstats.org/api/indicator"


class ASEANClient(BaseAPIClient):
    def __init__(self):
        super().__init__(
            source_name="ASEANstats",
            base_url=ASEAN_API_BASE,
            api_key_env=None,
            api_key_required=False,
            timeout=120,
        )
        self.session.headers.update(
            {
                "User-Agent": os.getenv(
                    "ASEAN_HTTP_USER_AGENT",
                    "VELTRIXIA-OSINT/1.0 (+https://github.com)",
                ),
                "Accept": "application/json",
            }
        )

    def get_indicator(self, indicator_code: str) -> List[Dict[str, Any]]:
        url = f"{ASEAN_API_BASE}/{indicator_code}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            text = (response.text or "").strip()
            if not text.startswith("["):
                logger.warning(
                    "ASEAN indicator %s returned non-JSON payload (%s chars)",
                    indicator_code,
                    len(text),
                )
                return []
            payload = json.loads(text)
            return payload if isinstance(payload, list) else []
        except Exception as exc:
            logger.error("ASEAN fetch failed for %s: %s", indicator_code, exc)
            return []

    def fetch_indicator_observations(
        self,
        indicator_code: str,
        *,
        aggregate_host_code: str = "ASEAN",
        max_observations: int = 60,
    ) -> List[Dict[str, Any]]:
        rows = self.get_indicator(indicator_code)
        parsed: List[Dict[str, Any]] = []
        for row in rows:
            host_code = str(row.get("Host Country Code", "")).strip()
            if aggregate_host_code and host_code != aggregate_host_code:
                continue
            normalized = normalize_asean_row(row)
            if normalized:
                parsed.append(normalized)
        parsed.sort(key=lambda r: r["date"], reverse=True)
        return parsed[:max_observations]


def normalize_asean_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    year = row.get("year") or row.get("Year")
    if year is None:
        return None
    try:
        dt = date(int(str(year).strip()), 1, 1)
    except ValueError:
        return None
    val = parse_asean_value(row.get("Value") or row.get("value"))
    if val is None:
        return None
    return {
        "date": dt.isoformat(),
        "value": val,
        "period_label": str(year),
        "raw": row,
    }


def parse_asean_value(value: Any) -> Optional[float]:
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
