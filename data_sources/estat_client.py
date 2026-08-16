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

from data_sources.base_client import BaseAPIClient, redact_credentials

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
        narrowing: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Call getStatsData and return raw JSON.
        """
        params = {
            "appId": self.api_key,
            "statsDataId": stats_data_id,
            "metaGetFlg": meta_get_flg,
            # "Y" returns counts only and omits VALUE rows (API 3.0 manual §4.3).
            "cntGetFlg": "N",
            "sectionHeaderFlg": "1",
            "limit": limit,
            "startPosition": start_position,
        }
        if narrowing:
            for key, value in narrowing.items():
                if value:
                    params[key] = value
        try:
            return self.get_json(ESTAT_GET_STATS_DATA_PATH, params=params)
        except Exception as exc:
            # appId is a query parameter, so the HTTPError message carries it.
            safe = redact_credentials(exc)
            logger.error("e-Stat getStatsData failed for %s: %s", stats_data_id, safe)
            return {"error": safe, "stats_data_id": stats_data_id}

    def get_stats_data_observations(
        self,
        stats_data_id: str,
        max_observations: int = 60,
        *,
        narrowing: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch table values and return normalized observation rows (newest first).
        """
        raw = self.get_stats_data(stats_data_id, limit=100_000, meta_get_flg="Y", narrowing=narrowing)
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
    def _build_time_label_map(response: Dict[str, Any]) -> Dict[str, str]:
        """Map TIME-axis @code -> @name (e.g. '0500100' -> '201801') from CLASS_INF, if present."""
        root = response.get("GET_STATS_DATA") or response.get("getStatsData") or {}
        stat = root.get("STATISTICAL_DATA") or root.get("statisticalData") or {}
        class_inf = (stat.get("CLASS_INF") or {}).get("CLASS_OBJ") or []
        if isinstance(class_inf, dict):
            class_inf = [class_inf]
        out: Dict[str, str] = {}
        for obj in class_inf:
            if not isinstance(obj, dict) or obj.get("@id") != "time":
                continue
            cls = obj.get("CLASS") or []
            if isinstance(cls, dict):
                cls = [cls]
            for item in cls:
                if isinstance(item, dict) and item.get("@code") is not None:
                    out[str(item.get("@code"))] = str(item.get("@name") or "")
        return out

    @staticmethod
    def _parse_value_rows(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        root = response.get("GET_STATS_DATA") or response.get("getStatsData") or {}
        stat = root.get("STATISTICAL_DATA") or root.get("statisticalData") or {}
        data = stat.get("DATA") or stat.get("data") or {}
        values = data.get("VALUE") or data.get("value") or []
        if not values:
            data_inf = stat.get("DATA_INF") or stat.get("dataInf") or {}
            if isinstance(data_inf, dict):
                values = data_inf.get("VALUE") or data_inf.get("value") or []
        if isinstance(values, dict):
            values = [values]

        time_labels = EStatClient._build_time_label_map(response)

        parsed: List[Dict[str, Any]] = []
        for cell in values:
            if not isinstance(cell, dict):
                continue
            time_code = cell.get("@time") or cell.get("time") or cell.get("@cat01")
            val = _extract_numeric(cell)
            if val is None:
                continue
            # Prefer the TIME-axis @name (true YYYYMM) when available (METI IIP encodes
            # @time as an opaque serial; @name carries the real period). Fall back to
            # parsing @time directly (e.g. CPI tables where @time is already YYYYMM...).
            label = time_labels.get(str(time_code)) if time_code is not None else None
            if label:
                # Labelled table (e.g. METI IIP numeric '201801', CPI kanji '2026年5月').
                # If the label is a known non-monthly aggregate (年度/年/期), DROP the row —
                # never fall back to the raw @time serial, which would misparse e.g.
                # FY '2021100000' as October and collide with the real month.
                dt = _parse_yyyymm_label(label)
                if dt is None:
                    continue
                period = label
            else:
                # Label-less table: fall back to parsing the @time code directly.
                dt = parse_estat_time_to_date(str(time_code) if time_code else "")
                if dt is None:
                    continue
                period = str(time_code)
            parsed.append(
                {
                    "date": dt.isoformat(),
                    "value": val,
                    "period_label": period,
                    "raw": cell,
                }
            )
        return parsed


def _parse_yyyymm_label(label: str) -> Optional[date]:
    """
    Parse an e-Stat TIME-axis @name into a monthly date.
    Handles two label formats and rejects non-monthly aggregates:
      - numeric  '201801'        -> 2018-01  (METI IIP)
      - kanji    '2026年5月'      -> 2026-05  (CPI)
    Non-monthly labels ('2025年度', '2025年' annual, weight rows, etc.) -> None.
    """
    if not label:
        return None
    text = str(label)
    # Reject explicit non-monthly aggregates outright.
    if ("年度" in text) or ("年計" in text) or ("期" in text):
        return None
    # Kanji form: YYYY年M月
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", text)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
    else:
        # Numeric form: exactly YYYYMM (6 digits). Anything else is not a plain month.
        s = re.sub(r"\D", "", text)
        if len(s) != 6:
            return None
        y, mo = int(s[:4]), int(s[4:6])
    if y < 1900 or y > 2100 or not (1 <= mo <= 12):
        return None
    return date(y, mo, 1)


def parse_estat_time_to_date(time_code: str) -> Optional[date]:
    """
    Parse e-Stat @time codes (e.g. 2024010000, 202301, 2023) to calendar date.
    """
    digits = re.sub(r"\D", "", time_code or "")
    if len(digits) < 4:
        return None
    year = int(digits[:4])
    if year < 1900 or year > 2100:
        return None
    if len(digits) >= 6:
        month = int(digits[4:6])
        if not (1 <= month <= 12):
            return None  # month '00' = annual/aggregate row (e.g. CPI YYYY000000) -> drop, don't clamp to Jan
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
