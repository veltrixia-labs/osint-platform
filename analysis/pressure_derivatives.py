"""
analysis/pressure_derivatives.py

Momentum & Acceleration Gauge — Velocity/Acceleration Derivatives
------------------------------------------------------------------
Maintains a lightweight in-memory rolling buffer of intensity snapshots
per strategic domain across successive `/api/insights/pro` poll cycles.

V = dI/dt  (first derivative — "how fast is risk moving?")
A = d²I/dt²  (second derivative — "is that movement accelerating?")

Design:
  - Module-level deque (maxlen=6) per domain — stateless across restarts,
    which is acceptable for a real-time display gauge.
  - Called from build_pro_insights_payload() to mutate risk_summary in-place.
  - Pure-Python, no external dependencies.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

# ── Constants ──────────────────────────────────────────────────────────────────

# Number of historical intensity snapshots to retain per domain
_HISTORY_LEN: int = 6

# Thresholds for arrow labels
_V_HIGH: float = 0.4        # velocity magnitude = high
_A_HIGH: float = 0.15       # acceleration magnitude = high (burst potential)

STRATEGIC_TOPICS = [
    "energy_resource_risk",
    "global_market_intelligence",
    "crypto_geopolitics",
    "ai_semiconductor_intelligence",
    "defense_technology",
    "supply_chain_intelligence",
]


# ── Module-level rolling history ───────────────────────────────────────────────
# Each entry: (unix_timestamp: float, intensity: float)

_history: dict[str, deque[tuple[float, float]]] = {
    t: deque(maxlen=_HISTORY_LEN) for t in STRATEGIC_TOPICS
}


# ── Derivative computation ─────────────────────────────────────────────────────

def _velocity(buf: deque[tuple[float, float]]) -> float:
    """
    Central finite difference over the full buffer.
    V ≈ (I_last - I_first) / (t_last - t_first) in units per second.
    Scaled to per-hour for readability.
    """
    if len(buf) < 2:
        return 0.0
    t0, i0 = buf[0]
    t1, i1 = buf[-1]
    dt = t1 - t0  # seconds
    if dt < 1.0:
        return 0.0
    return (i1 - i0) / (dt / 3600.0)  # intensity units per hour


def _acceleration(buf: deque[tuple[float, float]]) -> float:
    """
    Estimate A = d²I/dt² using three-point stencil over first/mid/last.
    """
    if len(buf) < 3:
        return 0.0

    pts = list(buf)
    # Use first, middle, last
    t0, i0 = pts[0]
    mid_idx = len(pts) // 2
    t1, i1 = pts[mid_idx]
    t2, i2 = pts[-1]

    dt1 = (t1 - t0) / 3600.0
    dt2 = (t2 - t1) / 3600.0

    if dt1 < 1e-6 or dt2 < 1e-6:
        return 0.0

    v1 = (i1 - i0) / dt1
    v2 = (i2 - i1) / dt2
    dt_mid = (t2 - t0) / 7200.0  # half total span in hours
    if dt_mid < 1e-6:
        return 0.0
    return (v2 - v1) / dt_mid


def _velocity_label(v: float) -> str:
    if v > _V_HIGH:
        return "rising"
    if v < -_V_HIGH:
        return "falling"
    return "stable"


def _acceleration_label(a: float) -> str:
    if a > _A_HIGH:
        return "accelerating"
    if a < -_A_HIGH:
        return "decelerating"
    return "stable"


# ── Public API ─────────────────────────────────────────────────────────────────

def enrich_risk_summary_with_derivatives(
    risk_summary: dict[str, Any],
    *,
    now_ts: float | None = None,
) -> None:
    """
    Mutate each domain dict in `risk_summary` in-place, adding:
        velocity         : float   (intensity units / hour)
        acceleration     : float
        v_label          : str     "rising" | "falling" | "stable"
        a_label          : str     "accelerating" | "decelerating" | "stable"

    Simultaneously appends the current intensity snapshot to the rolling buffer.
    """
    ts = now_ts if now_ts is not None else time.time()

    for topic in STRATEGIC_TOPICS:
        stat = risk_summary.get(topic)
        if not isinstance(stat, dict):
            continue

        intensity: float = float(stat.get("intensity") or 0.0)

        # Append snapshot to rolling buffer
        buf = _history[topic]
        buf.append((ts, intensity))

        # Compute derivatives
        v = _velocity(buf)
        a = _acceleration(buf)

        stat["velocity"] = round(v, 4)
        stat["acceleration"] = round(a, 4)
        stat["v_label"] = _velocity_label(v)
        stat["a_label"] = _acceleration_label(a)
