"""
CFTC COT catalog: maps strategic domains to the relevant futures market.

Each entry pairs a `market_and_exchange` string (Socrata key) with the
strategic topic + macro ticker its positioning best informs. Used by the
Hidden Accumulation engine and the COT sync job.
"""
from __future__ import annotations

from typing import Any, Dict, List

CFTC_COT_CATALOG: List[Dict[str, Any]] = [
    {
        # Verified via Socrata 6dca-aqww 2026-05-25
        "market_and_exchange": "CRUDE OIL, LIGHT SWEET-WTI - ICE FUTURES EUROPE",
        "label": "WTI Crude Oil",
        "macro_ticker": "DCOILWTICO",
        "strategic_topic": "energy_resource_risk",
        "is_tracked": True,
    },
    {
        "market_and_exchange": "GOLD - COMMODITY EXCHANGE INC.",
        "label": "Gold",
        "macro_ticker": "GOLDAMGBD228NLBM",   # FRED gold benchmark (not in tradeable list yet)
        "strategic_topic": "global_market_intelligence",
        "is_tracked": True,
    },
    {
        "market_and_exchange": "COPPER- #1 - COMMODITY EXCHANGE INC.",
        "label": "Copper (Grade #1)",
        "macro_ticker": "PCOPPUSDM",
        "strategic_topic": "supply_chain_intelligence",
        "is_tracked": True,
    },
    {
        # 10Y T-notes pair well with our DGS10 macro ticker
        "market_and_exchange": "10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",
        "label": "10Y US Treasury Notes",
        "macro_ticker": "DGS10",
        "strategic_topic": "global_market_intelligence",
        "is_tracked": True,
    },
    {
        "market_and_exchange": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
        "label": "Bitcoin Futures",
        "macro_ticker": None,
        "strategic_topic": "crypto_geopolitics",
        "is_tracked": True,
    },
    {
        "market_and_exchange": "VIX FUTURES - CBOE FUTURES EXCHANGE",
        "label": "VIX Futures",
        "macro_ticker": "VIXCLS",
        "strategic_topic": "global_market_intelligence",
        "is_tracked": True,
    },
]


def get_tracked_cot_markets() -> List[Dict[str, Any]]:
    """Return the subset flagged for weekly sync (avoid scraping all 500+ markets)."""
    return [c for c in CFTC_COT_CATALOG if c.get("is_tracked")]


def get_cot_market_for_macro(macro_ticker: str) -> Dict[str, Any] | None:
    """Reverse lookup: from FRED macro ticker → COT market (for divergence engine)."""
    for entry in CFTC_COT_CATALOG:
        if entry.get("macro_ticker") == macro_ticker:
            return entry
    return None


def get_cot_market_for_topic(strategic_topic: str) -> Dict[str, Any] | None:
    """First COT market mapped to a strategic topic."""
    for entry in CFTC_COT_CATALOG:
        if entry.get("strategic_topic") == strategic_topic:
            return entry
    return None
