"""
analysis/lead_lag_engine.py

Risk Contagion & Lead-Lag Tracker
----------------------------------
Computes pairwise Cross-Correlation Functions (CCF) between the 6 strategic
sector time-series using true historical AlertLog data.

Design principles:
  - Pure-Python: no numpy required (arrays of 24 points, math is trivial).
  - Authentic data: Queries real database records to build the time-series.
  - Returns only non-trivial pairs (|R| >= MIN_CORRELATION, lag != 0).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AlertLog
from analysis.pro_domain_config import STRATEGIC_DOMAINS, infer_domain_from_topic
from analysis.intensity_pressure import raw_intensity_from_alert, ui_display_intensity

# ── Constants ──────────────────────────────────────────────────────────────────

# Re-exported for backward compatibility; canonical definition lives in
# `analysis.pro_domain_config.STRATEGIC_DOMAINS`.
STRATEGIC_TOPICS = STRATEGIC_DOMAINS

# Only emit pairs with meaningful cross-correlation
MIN_CORRELATION: float = 0.38

# Max lag window to test (±hours). For a 24-point series each point = 1 hour.
MAX_LAG: int = 8

# Maximum pairs to return (sorted by |R| descending)
MAX_PAIRS: int = 8


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mean(series: list[float]) -> float:
    return sum(series) / len(series) if series else 0.0


def _std(series: list[float], mean: float) -> float:
    if len(series) < 2:
        return 0.0
    variance = sum((x - mean) ** 2 for x in series) / len(series)
    return math.sqrt(variance)


def _cross_correlation(x: list[float], y: list[float], lag: int) -> float:
    """
    Pearson cross-correlation of x with y shifted by `lag` positions.
    Positive lag → y lags behind x (x is the leader).
    """
    n = len(x)
    if n < 4:
        return 0.0

    # Build lagged pair
    if lag >= 0:
        xi = x[:n - lag]
        yi = y[lag:]
    else:
        xi = x[-lag:]
        yi = y[:n + lag]

    m = len(xi)
    if m < 3:
        return 0.0

    mx = _mean(xi)
    my = _mean(yi)
    sx = _std(xi, mx)
    sy = _std(yi, my)

    if sx == 0.0 or sy == 0.0:
        return 0.0

    cov = sum((xi[i] - mx) * (yi[i] - my) for i in range(m)) / m
    return cov / (sx * sy)


# ── Public API ─────────────────────────────────────────────────────────────────

async def compute_lead_lag_matrix(
    db: AsyncSession,
    n_points: int = 24,
) -> list[dict[str, Any]]:
    """
    Compute pairwise CCF between all 6 strategic domains using historical data.

    Returns a list of dicts:
        {
            "source": str,       # leading domain (causes the shift)
            "target": str,       # lagging domain
            "lag_hours": float,  # positive = source leads target
            "correlation": float # peak |R| at optimal lag
        }

    Sorted by |correlation| descending, trimmed to MAX_PAIRS.
    """
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=n_points)
    
    stmt = select(AlertLog).where(
        AlertLog.triggered_at >= lookback,
        AlertLog.suppressed == False  # noqa: E712
    ).order_by(AlertLog.triggered_at.asc())
    
    alerts = list((await db.execute(stmt)).scalars().all())
    
    # Initialize series map
    series_map: dict[str, list[float]] = {topic: [0.0] * n_points for topic in STRATEGIC_DOMAINS}

    for alert in alerts:
        topic = infer_domain_from_topic(alert.topic or "")
        if topic not in series_map:
            continue
        
        # Determine which bucket this alert falls into (0 to n_points - 1)
        alert_ts = alert.triggered_at
        if alert_ts.tzinfo is None:
            alert_ts = alert_ts.replace(tzinfo=timezone.utc)
            
        hours_since_lookback = (alert_ts - lookback).total_seconds() / 3600.0
        bucket_idx = int(math.floor(hours_since_lookback))
        bucket_idx = max(0, min(n_points - 1, bucket_idx))
        
        raw_int = raw_intensity_from_alert(alert)
        ui_int = ui_display_intensity(raw_int)
        
        # Max pooling per hour
        if ui_int > series_map[topic][bucket_idx]:
            series_map[topic][bucket_idx] = ui_int
            
    # Forward-fill to avoid artificial zero variance dropping R to 0
    # If there was an alert at hour 2, but nothing at hour 3, carry hour 2's intensity forward with slight decay.
    for topic in STRATEGIC_DOMAINS:
        series = series_map[topic]
        for i in range(1, n_points):
            if series[i] == 0.0 and series[i-1] > 0.0:
                series[i] = series[i-1] * 0.95  # 5% hourly decay

    active_topics = [t for t in STRATEGIC_DOMAINS if any(v > 0 for v in series_map[t])]
    if len(active_topics) < 2:
        return []

    pairs: list[dict[str, Any]] = []

    for i, src in enumerate(active_topics):
        for tgt in active_topics[i + 1:]:
            x = series_map[src]
            y = series_map[tgt]

            best_r: float = 0.0
            best_lag: int = 0

            for lag in range(-MAX_LAG, MAX_LAG + 1):
                r = _cross_correlation(x, y, lag)
                if abs(r) > abs(best_r):
                    best_r = r
                    best_lag = lag

            if abs(best_r) < MIN_CORRELATION:
                continue

            # Determine direction: positive lag → src leads tgt
            if best_lag >= 0:
                source, target, lag_h = src, tgt, float(best_lag)
            else:
                source, target, lag_h = tgt, src, float(-best_lag)

            # Skip zero-lag (simultaneous) — not directional
            if lag_h == 0.0:
                continue

            pairs.append({
                "source": source,
                "target": target,
                "lag_hours": round(lag_h, 1),
                "correlation": round(best_r, 3),
            })

    # Sort by absolute correlation descending
    pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)
    return pairs[:MAX_PAIRS]
