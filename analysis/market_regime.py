"""
Market Regime Engine
====================

Rule-based, mathematically grounded classifier that turns 30-day rate-of-change
signals from three benchmark FRED series into one of six macro regimes.

Inputs (all FRED):
    DGS10        — US 10-Year Treasury Yield  (rates proxy)
    DCOILWTICO   — WTI Crude Oil              (oil/inflation proxy)
    VIXCLS       — CBOE VIX                   (equity risk proxy)

Output:
    {
        "regime": "Reflation",
        "emoji":  "🔥",
        "accent_color": "#f97316",
        "glow_color":   "rgba(249,115,22,0.45)",
        "rationale":    "...short human-readable explanation...",
        "components": {
            "rates_roc_pct": +6.2,
            "oil_roc_pct":   +8.4,
            "vix_roc_pct":   -3.1
        },
        "observation_window_days": 30,
        "generated_at": "2026-05-25T..."
    }
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ExternalObservation

logger = logging.getLogger(__name__)

# Component series IDs. Kept as constants so a downstream consumer (e.g.
# /options endpoint) can introspect what the regime depends on.
SERIES_RATES = "DGS10"
SERIES_OIL = "DCOILWTICO"
SERIES_VIX = "VIXCLS"

REGIME_WINDOW_DAYS = 30
# Lookup window for the latest available observation pair. Real FRED daily
# series only update on trading days, so we look back a generous buffer.
_FETCH_LOOKBACK_DAYS = REGIME_WINDOW_DAYS * 3

# Thresholds (all expressed as percentage RoC over the 30-day window).
_RATES_TRIGGER_PCT = 5.0   # 10Y yield move that counts as a directional break
_OIL_TRIGGER_PCT = 5.0     # WTI swing
_VIX_SPIKE_PCT = 15.0      # VIX surge that signals risk-off


_REGIME_META: Dict[str, Dict[str, str]] = {
    "Stagflation": {"emoji": "⚠️", "accent_color": "#dc2626", "glow_color": "rgba(220,38,38,0.50)"},
    "Reflation":   {"emoji": "🔥", "accent_color": "#f97316", "glow_color": "rgba(249,115,22,0.45)"},
    "Tightening":  {"emoji": "📉", "accent_color": "#f59e0b", "glow_color": "rgba(245,158,11,0.40)"},
    "Recession":   {"emoji": "🧊", "accent_color": "#38bdf8", "glow_color": "rgba(56,189,248,0.45)"},
    "Stimulus":    {"emoji": "💧", "accent_color": "#22d3ee", "glow_color": "rgba(34,211,238,0.45)"},
    "Goldilocks":  {"emoji": "✨", "accent_color": "#10b981", "glow_color": "rgba(16,185,129,0.40)"},
    "Indeterminate": {"emoji": "❔", "accent_color": "#94a3b8", "glow_color": "rgba(148,163,184,0.30)"},
}


async def _latest_value_and_roc(
    db: AsyncSession,
    series_id: str,
    window_days: int = REGIME_WINDOW_DAYS,
) -> Optional[float]:
    """
    Return the percentage rate-of-change of `series_id` over the most recent
    ``window_days`` observations, or None if insufficient data is available.

    Uses the latest observation as the endpoint and the observation closest to
    (latest - window_days) as the baseline. Both must have non-null, non-zero
    base values to produce a meaningful percentage.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=_FETCH_LOOKBACK_DAYS)

    stmt = (
        select(ExternalObservation.date, ExternalObservation.value)
        .where(
            and_(
                ExternalObservation.series_id == series_id,
                ExternalObservation.date >= since.date(),
            )
        )
        .order_by(ExternalObservation.date.asc())
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return None

    # Drop nulls
    obs = [(r[0], float(r[1])) for r in rows if r[1] is not None]
    if len(obs) < 2:
        return None

    latest_date, latest_value = obs[-1]
    if latest_value == 0:
        return None

    # Find baseline observation closest to (latest_date - window_days), prior to or equal.
    target = latest_date - timedelta(days=window_days)
    baseline = None
    for d, v in obs:
        if d <= target:
            baseline = (d, v)
        else:
            break
    if baseline is None or baseline[1] == 0:
        return None

    return ((latest_value - baseline[1]) / abs(baseline[1])) * 100.0


def classify_regime(
    rates_roc: Optional[float],
    oil_roc: Optional[float],
    vix_roc: Optional[float],
) -> str:
    """
    Decision tree over signed RoC percentages. Any None input is treated as
    'no signal' and skips its branch — the function never crashes on partial data.
    """
    if rates_roc is None and oil_roc is None and vix_roc is None:
        return "Indeterminate"

    rates_up = rates_roc is not None and rates_roc > _RATES_TRIGGER_PCT
    rates_dn = rates_roc is not None and rates_roc < -_RATES_TRIGGER_PCT
    oil_up = oil_roc is not None and oil_roc > _OIL_TRIGGER_PCT
    oil_dn = oil_roc is not None and oil_roc < -_OIL_TRIGGER_PCT
    vix_spike = vix_roc is not None and vix_roc > _VIX_SPIKE_PCT

    if rates_up and oil_up and vix_spike:
        return "Stagflation"
    if rates_up and oil_up:
        return "Reflation"
    if rates_up and oil_dn:
        return "Tightening"
    if rates_dn and oil_dn:
        return "Recession"
    if rates_dn and oil_up:
        return "Stimulus"
    return "Goldilocks"


def _rationale(
    regime: str,
    rates_roc: Optional[float],
    oil_roc: Optional[float],
    vix_roc: Optional[float],
) -> str:
    """Short, neutral, mathematically grounded one-liner per regime."""
    def fmt(x: Optional[float]) -> str:
        return "n/a" if x is None else f"{x:+.2f}%"

    parts: List[str] = [
        f"30-day RoC — Rates(DGS10): {fmt(rates_roc)}",
        f"Oil(WTI): {fmt(oil_roc)}",
        f"VIX: {fmt(vix_roc)}",
    ]
    base = " · ".join(parts) + ". "

    detail = {
        "Stagflation": "Rates rising with oil pressure AND volatility spike — classic stagflation co-signal.",
        "Reflation":   "Rates rising alongside oil — markets pricing in growth + inflation reflation.",
        "Tightening":  "Rates rising while oil falls — restrictive monetary stance pulling demand expectations down.",
        "Recession":   "Rates falling with oil falling — demand contraction; defensive positioning warranted.",
        "Stimulus":    "Rates falling while oil rises — accommodative monetary stance with commodity reflation.",
        "Goldilocks":  "No component crosses the directional trigger — balanced, range-bound macro environment.",
        "Indeterminate": "Insufficient observations to classify; populate the FRED catalog and retry.",
    }
    return base + detail.get(regime, "")


async def compute_market_regime(db: AsyncSession) -> Dict[str, Any]:
    """
    Full pipeline: fetch 3 RoC components, classify, return structured payload.
    Safe to call from any FastAPI route — no exceptions propagate (a missing
    series collapses to the Indeterminate regime with explanatory rationale).
    """
    try:
        rates_roc = await _latest_value_and_roc(db, SERIES_RATES)
        oil_roc = await _latest_value_and_roc(db, SERIES_OIL)
        vix_roc = await _latest_value_and_roc(db, SERIES_VIX)
    except Exception as exc:
        logger.warning("Market regime fetch failed: %s", exc, exc_info=True)
        rates_roc = oil_roc = vix_roc = None

    regime = classify_regime(rates_roc, oil_roc, vix_roc)
    meta = _REGIME_META.get(regime, _REGIME_META["Indeterminate"])

    return {
        "regime": regime,
        "label": regime.upper() + " MODE",
        "emoji": meta["emoji"],
        "accent_color": meta["accent_color"],
        "glow_color": meta["glow_color"],
        "rationale": _rationale(regime, rates_roc, oil_roc, vix_roc),
        "components": {
            "rates_roc_pct": None if rates_roc is None else round(rates_roc, 3),
            "oil_roc_pct":   None if oil_roc   is None else round(oil_roc, 3),
            "vix_roc_pct":   None if vix_roc   is None else round(vix_roc, 3),
            "series_ids": {
                "rates": SERIES_RATES,
                "oil":   SERIES_OIL,
                "vix":   SERIES_VIX,
            },
            "trigger_thresholds_pct": {
                "rates": _RATES_TRIGGER_PCT,
                "oil":   _OIL_TRIGGER_PCT,
                "vix":   _VIX_SPIKE_PCT,
            },
        },
        "observation_window_days": REGIME_WINDOW_DAYS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
