"""
analysis/lead_lag_engine.py

Risk Contagion & Lead-Lag Tracker
----------------------------------
Computes pairwise Cross-Correlation Functions (CCF) between the 6 strategic
sector time-series using intensity snapshots already available in `risk_summary`.

Design principles:
  - Pure-Python: no numpy required (arrays of 24 points, math is trivial).
  - Stateless: called once per `/api/insights/pro` polling cycle.
  - Returns only non-trivial pairs (|R| >= MIN_CORRELATION, lag != 0).
"""

from __future__ import annotations

import math
from typing import Any

# ── Constants ──────────────────────────────────────────────────────────────────

STRATEGIC_TOPICS = [
    "energy_resource_risk",
    "global_market_intelligence",
    "crypto_geopolitics",
    "ai_semiconductor_intelligence",
    "defense_technology",
    "supply_chain_intelligence",
]

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


def _reconstruct_series(stat: dict[str, Any], n_points: int = 24) -> list[float]:
    """
    Reconstruct an approximate time-series for a domain from its
    scalar pressure metrics (intensity + delta as linear slope + wave).
    This is the same seeded-wave logic used in market_pulse.ts but in Python,
    ensuring the backend CCF is computed on the same modelled surface.
    """
    intensity: float = float(stat.get("intensity") or 0.0)
    delta: float = float(stat.get("intensity_delta") or 0.0)

    base = min(1.0, max(0.08, intensity / 10.0))
    d = delta * 0.04
    points: list[float] = []
    for i in range(n_points):
        t = i / max(1, n_points - 1)
        drift = d * (t - 0.5)
        # Lightweight deterministic wave (no external seed needed here —
        # we use index alone so the pattern is stable per-call)
        wave = math.sin(i * 1.35 + intensity * 0.3) * 0.08
        val = min(1.0, max(0.04, base + drift + wave))
        points.append(val)
    return points


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_lead_lag_matrix(
    risk_summary: dict[str, Any],
    n_points: int = 24,
) -> list[dict[str, Any]]:
    """
    Compute pairwise CCF between all 6 strategic domains.

    Returns a list of dicts:
        {
            "source": str,       # leading domain (causes the shift)
            "target": str,       # lagging domain
            "lag_hours": float,  # positive = source leads target
            "correlation": float # peak |R| at optimal lag
        }

    Sorted by |correlation| descending, trimmed to MAX_PAIRS.
    """
    # Build series for every domain that has active signals
    series_map: dict[str, list[float]] = {}
    for topic in STRATEGIC_TOPICS:
        stat = risk_summary.get(topic)
        if not stat:
            continue
        intensity = float(stat.get("intensity") or 0.0)
        if intensity <= 0.0:
            continue
        series_map[topic] = _reconstruct_series(stat, n_points)

    active_topics = list(series_map.keys())
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
