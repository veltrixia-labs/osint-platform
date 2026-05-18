"""
e-Stat API Client (Japanese government statistics).

Fetches statistical tables via the e-Stat REST API (JSON).
Requires ESTAT_APP_ID from https://www.e-stat.go.jp/api/
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

# Official e-Stat API v3 JSON endpoint (getStatsData)
ESTAT_GET_STATS_DATA_PATH = (
    "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
)


class EStatClient(BaseAPIClient):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            source_name="e-Stat",
            base_url="https://api.e-stat.go.jp",
            api_key_env="ESTAT_APP_ID",
            api_key_required=True,
        )
        if api_key:
            self.api_key = api_key

    def get_stats_data(
        self,
        stats_data_id: str,
        *,
        limit: int = 100_000,
        start_position: int = 1,
        meta_get_flg: str = "N",
    ) -> Dict[str, Any]:
        """
        Call getStatsData and return raw JSON.
        """
        params = {
            "appId": self.api_key,
            "statsDataId": stats_data_id,
            "metaGetFlg": meta_get_flg,
            "cntGetFlg": "Y",
            "sectionHeaderFlg": "1",
            "limit": limit,
            "startPosition": start_position,
        }
        try:
            return self.get_json(ESTAT_GET_STATS_DATA_PATH, params=params)
        except Exception as exc:
            logger.error("e-Stat getStatsData failed for %s: %s", stats_data_id, exc)
            return {"error": str(exc), "stats_data_id": stats_data_id}

    def get_stats_data_observations(
        self,
        stats_data_id: str,
        max_observations: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Fetch table values and return normalized observation rows (newest first).
        """
        raw = self.get_stats_data(stats_data_id, limit=100_000)
        if raw.get("error"):
            return []

        if not self._is_success(raw):
            msg = self._result_message(raw)
            logger.error("e-Stat API error for %s: %s", stats_data_id, msg)
            return []

        rows = self._parse_value_rows(raw)
        if not rows:
            return []

        rows.sort(key=lambda r: r["date"], reverse=True)
        return rows[:max_observations]

    @staticmethod
    def _is_success(response: Dict[str, Any]) -> bool:
        root = response.get("GET_STATS_DATA") or response.get("getStatsData") or {}
        result = root.get("RESULT") or root.get("result") or {}
        status = result.get("STATUS") or result.get("status")
        if status is None:
            return bool(root.get("STATISTICAL_DATA") or root.get("statistical_data"))
        try:
            return int(status) == 0
        except (TypeError, ValueError):
            return str(status) in ("0", "00")

    @staticmethod
    def _result_message(response: Dict[str, Any]) -> str:
        root = response.get("GET_STATS_DATA") or {}
        result = root.get("RESULT") or {}
        return str(result.get("ERROR_MSG") or result.get("errorMsg") or "unknown error")

    @staticmethod
    def _parse_value_rows(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        root = response.get("GET_STATS_DATA") or response.get("getStatsData") or {}
        stat = root.get("STATISTICAL_DATA") or root.get("statisticalData") or {}
        data = stat.get("DATA") or stat.get("data") or {}
        values = data.get("VALUE") or data.get("value") or []
        if isinstance(values, dict):
            values = [values]

        parsed: List[Dict[str, Any]] = []
        for cell in values:
            if not isinstance(cell, dict):
                continue
            time_code = (
                cell.get("@time")
                or cell.get("time")
                or cell.get("@cat01")
            )
            val = _extract_numeric(cell)
            dt = parse_estat_time_to_date(str(time_code) if time_code else "")
            if dt is None or val is None:
                continue
            parsed.append(
                {
                    "date": dt.isoformat(),
                    "value": val,
                    "period_label": str(time_code),
                    "raw": cell,
                }
            )
        return parsed


def parse_estat_time_to_date(time_code: str) -> Optional[date]:
    """
    Parse e-Stat @time codes (e.g. 2024010000, 202301, 2023) to calendar date.
    """
    digits = re.sub(r"\D", "", time_code or "")
    if len(digits) < 4:
        return None
    year = int(digits[:4])
    if len(digits) >= 6:
        month = max(1, min(12, int(digits[4:6])))
        return date(year, month, 1)
    return date(year, 1, 1)


def _extract_numeric(cell: Dict[str, Any]) -> Optional[float]:
    for key in ("$", "value", "@value", "VALUE"):
        if key not in cell:
            continue
        raw = cell[key]
        if raw is None:
            continue
        text = str(raw).strip().replace(",", "")
        if text in ("", ".", "-", "…", "..."):
            return None
        try:
            return float(text)
        except ValueError:
            continue
    return None
