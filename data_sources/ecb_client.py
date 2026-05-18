"""
ECB Statistical Data Warehouse REST client (SDMX-JSON).

No API key required. Base: https://data-api.ecb.europa.eu/service/data/
(Legacy sdw-wsrest.ecb.europa.eu is deprecated and may not resolve.)
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

ECB_DATA_BASE = "https://data-api.ecb.europa.eu/service/data"


class ECBClient(BaseAPIClient):
    def __init__(self):
        super().__init__(
            source_name="ECB",
            base_url=ECB_DATA_BASE,
            api_key_env=None,
            api_key_required=False,
            timeout=60,
        )

    def get_series_data(
        self,
        series_key: str,
        *,
        last_n_observations: int = 60,
        format: str = "jsondata",
    ) -> Dict[str, Any]:
        """Fetch SDMX-JSON for one ECB series key (e.g. EXR/D.USD.EUR.SP00.A)."""
        key = series_key.strip("/")
        url = f"{ECB_DATA_BASE}/{key}"
        params = {
            "format": format,
            "lastNObservations": last_n_observations,
        }
        headers = {"Accept": "application/json"}
        try:
            return self.get_json(url, params=params, headers=headers)
        except Exception as exc:
            logger.error("ECB fetch failed for %s: %s", series_key, exc)
            return {"error": str(exc), "series_key": series_key}

    def fetch_series_observations(
        self,
        series_key: str,
        max_observations: int = 60,
    ) -> List[Dict[str, Any]]:
        """Fetch and normalize observations for one series."""
        raw = self.get_series_data(series_key, last_n_observations=max_observations)
        if raw.get("error"):
            return []
        return parse_sdmx_json_observations(raw, max_observations=max_observations)


def parse_sdmx_json_observations(
    payload: Dict[str, Any],
    *,
    max_observations: int = 60,
) -> List[Dict[str, Any]]:
    """
    Extract (period, value) pairs from ECB SDMX-JSON (jsondata) messages.
    Supports legacy layout: header / dataSets / structure.
    """
    datasets = payload.get("dataSets") or []
    if not datasets and payload.get("data"):
        data_block = payload["data"]
        if isinstance(data_block, dict):
            datasets = data_block.get("dataSets") or []
            structure = data_block.get("structure") or payload.get("structure") or {}
        else:
            structure = payload.get("structure") or {}
    else:
        structure = payload.get("structure") or {}

    if not datasets:
        return []

    time_index = _build_time_period_index(structure)
    parsed: List[Dict[str, Any]] = []

    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        ds_structure = dataset.get("structure") or structure
        if ds_structure and not time_index:
            time_index = _build_time_period_index(ds_structure)

        series_map = dataset.get("series") or {}
        for _series_key, series_body in series_map.items():
            if not isinstance(series_body, dict):
                continue
            observations = series_body.get("observations") or {}
            for obs_idx_str, obs_values in observations.items():
                row = _observation_from_index(
                    obs_idx_str, obs_values, time_index, series_body
                )
                if row:
                    parsed.append(row)

    parsed.sort(key=lambda r: r["date"], reverse=True)
    return parsed[:max_observations]


def _build_time_period_index(structure: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """Map observation dimension index -> TIME_PERIOD value metadata."""
    dims = (structure or {}).get("dimensions") or {}
    observation_dims = dims.get("observation") or []
    for dim in observation_dims:
        if not isinstance(dim, dict):
            continue
        if dim.get("id") == "TIME_PERIOD" or dim.get("role") == "time":
            values = dim.get("values") or []
            return {idx: val for idx, val in enumerate(values) if isinstance(val, dict)}
    return {}


def _observation_from_index(
    obs_idx_str: str,
    obs_values: Any,
    time_index: Dict[int, Dict[str, Any]],
    series_body: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    try:
        obs_idx = int(obs_idx_str)
    except (TypeError, ValueError):
        return None

    period_meta = time_index.get(obs_idx, {})
    period_id = period_meta.get("id") or period_meta.get("name")
    dt = parse_ecb_period(period_id)
    val = extract_sdmx_observation_value(obs_values)
    if dt is None or val is None:
        return None

    return {
        "date": dt.isoformat(),
        "value": val,
        "period_label": str(period_id) if period_id else None,
        "raw": {
            "observation_index": obs_idx,
            "observation": obs_values,
            "time_period": period_meta,
            "series_attributes": series_body.get("attributes"),
        },
    }


def parse_ecb_period(period: Any) -> Optional[date]:
    """Parse ECB TIME_PERIOD ids (daily, monthly, quarterly, annual)."""
    if period is None:
        return None
    text = str(period).strip()
    if not text:
        return None

    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            pass

    if re.match(r"^\d{4}-\d{2}$", text):
        try:
            return datetime.strptime(text, "%Y-%m").date()
        except ValueError:
            pass

    q_match = re.match(r"^(\d{4})-Q([1-4])$", text, re.I)
    if q_match:
        year, quarter = int(q_match.group(1)), int(q_match.group(2))
        month = (quarter - 1) * 3 + 1
        return date(year, month, 1)

    if re.match(r"^\d{4}$", text):
        return date(int(text), 1, 1)

    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def extract_sdmx_observation_value(obs_values: Any) -> Optional[float]:
    """
    SDMX-JSON observations are arrays; the first element is typically the measure.
    Example: [1.4529, 0, 0, null, null]
    """
    if obs_values is None:
        return None
    if isinstance(obs_values, (int, float)):
        return float(obs_values)
    if isinstance(obs_values, str):
        text = obs_values.strip().replace(",", "")
        if text in ("", ".", "-", "NaN"):
            return None
        try:
            return float(text)
        except ValueError:
            return None
    if isinstance(obs_values, list):
        for item in obs_values:
            val = extract_sdmx_observation_value(item)
            if val is not None:
                return val
        return None
    if isinstance(obs_values, dict):
        for key in ("obsValue", "value", "OBS_VALUE"):
            if key in obs_values:
                return extract_sdmx_observation_value(obs_values[key])
    return None
