"""
Statistical Mechanics — Market Entropy Engine
=============================================

Implements Shannon entropy `S = -Σ p_i ln(p_i)` over two orthogonal
distributions, then combines them into a single normalised entropy gauge.

Components
----------
1. **Topic dispersion** — how evenly spread the last 24h of alerts are across
   the six strategic domains. Even spread → high entropy → no dominant theme.
2. **Intensity dispersion** — how evenly the same alerts are spread across
   three intensity buckets (low / medium / high). High entropy → indecision.

Output
------
A single ``entropy_normalised`` value in [0, 1] suitable for the gauge UI,
plus the underlying component values for tooltips and the "BREAKOUT WARNING"
trigger (fires when ``entropy_normalised >= BREAKOUT_THRESHOLD``).

No new external dependencies — pure Python + math.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AlertLog
from analysis.pro_domain_config import STRATEGIC_DOMAINS, infer_domain_from_topic
from analysis.intensity_pressure import raw_intensity_from_alert, ui_display_intensity

logger = logging.getLogger(__name__)

# Window used for both topic and intensity dispersion. Kept in sync with the
# Pro-grade clustering window (24h) so the engine reads from the same logical
# regime as the Lead-Lag / Risk-Contagion matrices.
ENTROPY_WINDOW_HOURS = 24

# Three intensity buckets — chosen so the maximum component entropy is
# log(3) ≈ 1.0986. We then divide by log(N) so each component is in [0,1].
_INTENSITY_LOW_MAX = 3.5
_INTENSITY_MED_MAX = 6.5

# Breakout warning fires when normalised entropy crosses this floor. 0.78 was
# picked empirically: it corresponds to ~ "alerts span ≥5 of 6 domains AND ≥2
# of 3 intensity buckets", which historically precedes regime changes.
BREAKOUT_THRESHOLD = 0.78


def _shannon_entropy(probabilities: List[float]) -> float:
    """Plain Shannon entropy in nats. Treats p=0 as 0 (limit of x·ln(x))."""
    s = 0.0
    for p in probabilities:
        if p > 0:
            s -= p * math.log(p)
    return s


def _normalise(entropy_nats: float, n_states: int) -> float:
    """Divide by log(N) so a uniform distribution maps to exactly 1.0."""
    if n_states <= 1:
        return 0.0
    return entropy_nats / math.log(n_states)


def _bucket_intensity(value: float) -> str:
    if value < _INTENSITY_LOW_MAX:
        return "low"
    if value < _INTENSITY_MED_MAX:
        return "medium"
    return "high"


def _classify_regime(normalised: float) -> Dict[str, Any]:
    """
    Map a [0,1] entropy score to a label + UI accent. The gauge UI binds to
    this directly so the colour automatically tracks the value.
    """
    if normalised >= BREAKOUT_THRESHOLD:
        return {
            "label": "BREAKOUT WARNING",
            "emoji": "🌪️",
            "accent_color": "#dc2626",
            "glow_color": "rgba(220,38,38,0.55)",
            "interpretation": (
                "Alert flow is dispersed across nearly every domain and "
                "intensity bucket — classic pre-breakout indecision."
            ),
        }
    if normalised >= 0.55:
        return {
            "label": "ELEVATED",
            "emoji": "⚡",
            "accent_color": "#f59e0b",
            "glow_color": "rgba(245,158,11,0.45)",
            "interpretation": (
                "Multiple domains are firing in parallel — directional clarity "
                "has not yet emerged."
            ),
        }
    if normalised >= 0.30:
        return {
            "label": "BALANCED",
            "emoji": "✨",
            "accent_color": "#10b981",
            "glow_color": "rgba(16,185,129,0.40)",
            "interpretation": "Moderate dispersion — typical baseline conditions.",
        }
    return {
        "label": "FOCUSED",
        "emoji": "🎯",
        "accent_color": "#22d3ee",
        "glow_color": "rgba(34,211,238,0.40)",
        "interpretation": "Alert flow is concentrated — a single regime dominates the cycle.",
    }


async def compute_market_entropy(
    db: AsyncSession,
    *,
    window_hours: int = ENTROPY_WINDOW_HOURS,
) -> Dict[str, Any]:
    """
    Pull the last `window_hours` of non-suppressed AlertLog rows and compute
    two-component Shannon entropy. Returns a payload safe for direct JSON
    serialisation by FastAPI.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)

    stmt = (
        select(AlertLog)
        .where(
            AlertLog.triggered_at >= since,
            AlertLog.suppressed == False,  # noqa: E712
        )
    )
    try:
        alerts = list((await db.execute(stmt)).scalars().all())
    except Exception as exc:
        logger.warning("Entropy fetch failed: %s", exc, exc_info=True)
        alerts = []

    if not alerts:
        return _empty_payload(now, window_hours, reason="no_alerts")

    # --- Topic distribution -----------------------------------------------
    topic_counts: Dict[str, int] = {t: 0 for t in STRATEGIC_DOMAINS}
    intensity_counts: Dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    raw_intensities: List[float] = []

    for a in alerts:
        domain = infer_domain_from_topic(a.topic or "")
        if domain in topic_counts:
            topic_counts[domain] += 1
        raw = raw_intensity_from_alert(a)
        ui = ui_display_intensity(raw)
        raw_intensities.append(ui)
        intensity_counts[_bucket_intensity(ui)] += 1

    total = float(sum(topic_counts.values()))
    if total == 0:
        return _empty_payload(now, window_hours, reason="no_classified_alerts")

    topic_probs = [c / total for c in topic_counts.values()]
    topic_entropy_nats = _shannon_entropy(topic_probs)
    topic_norm = _normalise(topic_entropy_nats, len(topic_probs))

    total_i = float(sum(intensity_counts.values()))
    intensity_probs = [c / total_i for c in intensity_counts.values()] if total_i else [0.0, 0.0, 0.0]
    intensity_entropy_nats = _shannon_entropy(intensity_probs)
    intensity_norm = _normalise(intensity_entropy_nats, len(intensity_probs))

    # Combined gauge: weight topic dispersion higher (60/40) — the regime
    # signal we care about is "which sectors are firing", with intensity
    # dispersion as a secondary indicator of indecision.
    combined_norm = 0.6 * topic_norm + 0.4 * intensity_norm
    regime = _classify_regime(combined_norm)

    return {
        "entropy_normalised": round(combined_norm, 4),
        "topic_entropy_normalised": round(topic_norm, 4),
        "intensity_entropy_normalised": round(intensity_norm, 4),
        "topic_entropy_nats": round(topic_entropy_nats, 4),
        "intensity_entropy_nats": round(intensity_entropy_nats, 4),
        "n_alerts": len(alerts),
        "topic_distribution": topic_counts,
        "intensity_distribution": intensity_counts,
        "window_hours": window_hours,
        "breakout_threshold": BREAKOUT_THRESHOLD,
        "breakout_warning": combined_norm >= BREAKOUT_THRESHOLD,
        "regime_label": regime["label"],
        "regime_emoji": regime["emoji"],
        "accent_color": regime["accent_color"],
        "glow_color": regime["glow_color"],
        "interpretation": regime["interpretation"],
        "generated_at": now.isoformat(),
    }


def _empty_payload(now: datetime, window_hours: int, *, reason: str) -> Dict[str, Any]:
    """
    Honest empty-state: shows zero entropy + an explicit reason so the UI
    can render an informative placeholder (NOT a fake gauge value).
    """
    return {
        "entropy_normalised": 0.0,
        "topic_entropy_normalised": 0.0,
        "intensity_entropy_normalised": 0.0,
        "topic_entropy_nats": 0.0,
        "intensity_entropy_nats": 0.0,
        "n_alerts": 0,
        "topic_distribution": {t: 0 for t in STRATEGIC_DOMAINS},
        "intensity_distribution": {"low": 0, "medium": 0, "high": 0},
        "window_hours": window_hours,
        "breakout_threshold": BREAKOUT_THRESHOLD,
        "breakout_warning": False,
        "regime_label": "NO DATA",
        "regime_emoji": "❔",
        "accent_color": "#94a3b8",
        "glow_color": "rgba(148,163,184,0.30)",
        "interpretation": f"No alert flow in the last {window_hours}h ({reason}).",
        "generated_at": now.isoformat(),
    }
