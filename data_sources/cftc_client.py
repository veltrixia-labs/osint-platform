"""
CFTC Commitments of Traders (COT) Client.

Uses CFTC's Socrata public reporting endpoint — no API key required.
Each weekly report is keyed by (market_and_exchange_names, report_date_as_yyyy_mm_dd).

Data dictionary:
  https://publicreporting.cftc.gov/dataset/Commitments-of-Traders-Disaggregated-Futures-Only-Reports/72hh-3qpy

Schema columns we surface (all integers, contract counts):
  noncomm_positions_long_all     — large speculators (managed money)  long
  noncomm_positions_short_all    — large speculators                   short
  comm_positions_long_all        — commercial hedgers                  long
  comm_positions_short_all       — commercial hedgers                  short
  nonrept_positions_long_all     — small (non-reportable) traders      long
  nonrept_positions_short_all    — small traders                       short
  noncomm_postions_spread_all    — speculator spreads (NB: CFTC typo)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

CFTC_SOCRATA_BASE = "https://publicreporting.cftc.gov/resource"
# Legacy Futures-Only "Combined" report — single dataset covering commodities
# AND financial futures (Treasury Notes, VIX, Bitcoin) which the Disaggregated
# dataset (72hh-3qpy) lacks. Column schema is identical for the fields we use.
COT_DATASET_ID = "6dca-aqww"


class CFTCClient(BaseAPIClient):
    """Public Socrata API — no key required, generous rate limits."""

    def __init__(self) -> None:
        super().__init__(
            source_name="CFTC",
            base_url=CFTC_SOCRATA_BASE,
            api_key_env=None,
            api_key_required=False,
        )

    def fetch_market(
        self,
        market_and_exchange: str,
        *,
        limit: int = 52,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent weekly COT rows for one (market, exchange) pair.

        Example market_and_exchange:
            "CRUDE OIL, LIGHT SWEET-NYMEX"
            "GOLD-COMMODITY EXCHANGE INC."
            "COPPER-GRADE #1-COMMODITY EXCHANGE INC."
            "UST BOND-CHICAGO BOARD OF TRADE"
        """
        url = f"{CFTC_SOCRATA_BASE}/{COT_DATASET_ID}.json"
        params = {
            "$where": f"market_and_exchange_names='{market_and_exchange}'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": str(limit),
        }
        try:
            raw = self.get_json(url, params=params)
        except Exception as exc:
            logger.warning("CFTC fetch failed for %s: %s", market_and_exchange, exc)
            return []
        if not isinstance(raw, list):
            return []
        return [_normalize_cot_row(row) for row in raw if isinstance(row, dict)]


def _parse_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _parse_date(v: Any) -> Optional[str]:
    if not v:
        return None
    s = str(v)
    # Socrata returns either "2026-05-20T00:00:00.000" or "2026-05-20"
    for fmt, size in (("%Y-%m-%dT%H:%M:%S.%f", 23), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:size], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_cot_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Project Socrata fields into our COTReport storage schema."""
    return {
        "market_and_exchange": row.get("market_and_exchange_names") or "",
        "report_date": _parse_date(row.get("report_date_as_yyyy_mm_dd")),
        "yyyy_report_week_ww": row.get("yyyy_report_week_ww"),
        "open_interest_all": _parse_int(row.get("open_interest_all")),
        # Non-commercial (large speculators)
        "noncomm_long": _parse_int(row.get("noncomm_positions_long_all")),
        "noncomm_short": _parse_int(row.get("noncomm_positions_short_all")),
        "noncomm_spread": _parse_int(row.get("noncomm_postions_spread_all")),  # CFTC typo retained
        # Commercial (hedgers)
        "comm_long": _parse_int(row.get("comm_positions_long_all")),
        "comm_short": _parse_int(row.get("comm_positions_short_all")),
        # Non-reportable (small traders)
        "nonrept_long": _parse_int(row.get("nonrept_positions_long_all")),
        "nonrept_short": _parse_int(row.get("nonrept_positions_short_all")),
        "raw_json": row,
    }
