"""
Domain pressure scaling: uncapped raw intensity, asymptotic UI index, decaying baseline.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

UI_ASYMPTOTE = 10.0
ANOMALY_UI_THRESHOLD = 8.5
SUSTAINED_PRESSURE_HOURS = 4.0
BASELINE_HALF_LIFE_HOURS = 48.0
REIGNITE_RAW_FACTOR = 1.5


def raw_intensity_from_alert(alert: Any) -> float:
    """Uncapped internal intensity (metadata preferred, else AlertLog.intensity)."""
    meta = getattr(alert, "metadata_json", None)
    if isinstance(meta, dict):
        raw = meta.get("raw_intensity")
        if raw is not None:
            return max(0.0, float(raw))
    return max(0.0, float(getattr(alert, "intensity", None) or 0.0))


def ui_display_intensity(raw: float) -> float:
    """
    Map raw intensity to a 0–<10 UI index (tanh asymptote — never exactly 10.0).
    """
    if raw <= 0:
        return 0.0
    # raw 10→~8.4, 20→~9.6, 30→~9.8, 50→~9.95 (still room to move upward)
    display = UI_ASYMPTOTE * math.tanh(raw / 8.0)
    return round(display, 2)


def decayed_domain_baseline(
    alerts: list[Any],
    now: datetime,
    *,
    half_life_hours: float = BASELINE_HALF_LIFE_HOURS,
) -> float:
    """Time-decayed moving average of raw intensity (older highs fade toward 'new normal')."""
    if not alerts:
        return 0.0
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    ln2 = math.log(2)
    total_w = 0.0
    total_v = 0.0
    for alert in alerts:
        ts = getattr(alert, "triggered_at", None)
        if not ts:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - ts).total_seconds() / 3600.0)
        w = math.exp(-ln2 * age_h / half_life_hours)
        raw = raw_intensity_from_alert(alert)
        total_w += w
        total_v += w * raw
    return total_v / total_w if total_w > 0 else 0.0


def _alert_ts(alert: Any) -> datetime:
    ts = getattr(alert, "triggered_at", None) or datetime.min.replace(tzinfo=timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def pressure_onset_hours(alerts: list[Any], now: datetime, *, ui_threshold: float = ANOMALY_UI_THRESHOLD) -> float | None:
    """Hours since the start of the current elevated-pressure episode (UI >= threshold)."""
    if not alerts:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    ordered = sorted(alerts, key=_alert_ts)
    episode_start: datetime | None = None
    for alert in ordered:
        ui = ui_display_intensity(raw_intensity_from_alert(alert))
        if ui >= ui_threshold:
            if episode_start is None:
                episode_start = _alert_ts(alert)
        else:
            episode_start = None
    if episode_start is None:
        return None
    return max(0.0, (now - episode_start).total_seconds() / 3600.0)


def classify_pressure_badge(
    alerts: list[Any],
    now: datetime,
    *,
    ui_current: float,
) -> dict[str, Any] | None:
    """
    Time-based badge state for sector cards.
    - 0–4h elevated: ANOMALY DETECTED (urgent pulse)
    - 4h+ sustained high: SUSTAINED THREAT (muted)
    """
    if ui_current < ANOMALY_UI_THRESHOLD:
        return None
    hours = pressure_onset_hours(alerts, now)
    if hours is None:
        hours = 0.0
    if hours < SUSTAINED_PRESSURE_HOURS:
        return {
            "pressure_badge_variant": "anomaly",
            "pressure_badge_label": "ANOMALY DETECTED",
            "pressure_hours_elevated": round(hours, 1),
        }
    return {
        "pressure_badge_variant": "sustained",
        "pressure_badge_label": "SUSTAINED THREAT",
        "pressure_hours_elevated": round(hours, 1),
    }


def spike_vs_baseline(
    raw_current: float,
    baseline_raw: float,
    *,
    ui_delta: float,
    reignite_factor: float = REIGNITE_RAW_FACTOR,
) -> bool:
    """Detect fresh volatility using uncapped raw values (not UI ceiling)."""
    if baseline_raw > 0 and raw_current >= baseline_raw * reignite_factor:
        return True
    return ui_delta > 2.0


# ── Distributed intensity % (ratio → percentage) ─────────────────────────────
# Replaces the old saturating 100·tanh(raw/8) gauge. The percentage is a smooth
# function of the RATIO (raw_current / baseline). The upper segment is an
# ASYMPTOTIC POWER curve — 100 − 50·(1.5/ratio)^P — whose slope keeps decaying,
# so even huge ratios stay distinct integers instead of pinning at a flat 100%:
#     ratio  = 0.0x..1.0x   ->  0%..25%   (at/below baseline — gentle floor)
#     ratio  = 1.0x..1.5x   -> 25%..50%   (sub-spike build-up)
#     ratio  = 1.5x (gate)  -> 50%        (ELEVATED threshold, exact)
#     ratio  = 2.0x -> ~60%  ·  3.0x -> ~70%  ·  4.0x -> ~76%   (wide ELEVATED window)
#     ratio  = 5.0x -> 80%        (CRITICAL entry — deliberately delayed)
#     ratio  = 10x -> ~88%   ·  15x -> ~91%   ·  20x -> ~93%    (90%+ = black-swan)
# The 15% floor doubles as the live Alert Stream ground-floor: anything below
# (ratio < ~0.6x, i.e. well under baseline) is filtered out of the active feed.
PERCENT_BASELINE_PCT = 25.0               # ratio 1.0x → 25% (baseline volatility)
PERCENT_GATE_RATIO = REIGNITE_RAW_FACTOR  # 1.5x → 50%
PERCENT_STREAM_FLOOR = 15.0               # live-feed cutoff: drop pct < 15%
# Upper-tail stretch exponent. Soft slope tuned so the ELEVATED band (50-79%)
# spans a WIDE ratio window (1.5x-5x) — 2x→60, 3x→70, 4x→76 — only crossing into
# CRITICAL (>=80%) at 5.0x, and reaching 90%+ solely for 15x-20x black-swans.
_PERCENT_TAIL_EXP = 0.76


def percentage_from_ratio(ratio: float) -> float:
    """Map a raw/baseline ratio to a smoothly-distributed 0–100% intensity score."""
    if ratio <= 0.0:
        return 0.0
    if ratio <= 1.0:
        # 0x..1.0x → 0%..25% (gentle floor so at-baseline reads ~25%, not flat 0)
        return round(PERCENT_BASELINE_PCT * ratio, 1)
    if ratio <= PERCENT_GATE_RATIO:
        # 1.0x..1.5x → 25%..50% (linear ramp into the spike gate)
        return round(PERCENT_BASELINE_PCT + (ratio - 1.0) / (PERCENT_GATE_RATIO - 1.0) * (50.0 - PERCENT_BASELINE_PCT), 1)
    # 1.5x.. → asymptotic power curve 50%→100% (stretched tail; 100% only past ~100x)
    pct = 100.0 - (100.0 - 50.0) * (PERCENT_GATE_RATIO / ratio) ** _PERCENT_TAIL_EXP
    return round(min(100.0, pct), 1)


def severity_from_percentage(pct: float) -> str:
    """3-tier threat gate on the distributed percentage, SYNCHRONIZED with the
    frontend (alertThreatTier: ELEVATED_PCT=82, CRITICAL_PCT=92) so a signal's
    stored severity matches the tier the UI renders.

    0–81% → watch (sub-ELEVATED) · 82–91% → elevated · 92–100% → critical.
    """
    if pct >= 92.0:
        return "critical"
    if pct >= 82.0:
        return "elevated"
    return "watch"


def build_domain_pressure_metrics(
    domain_alerts: list[Any],
    prev_alerts: list[Any],
    now: datetime,
) -> dict[str, Any]:
    """Aggregate pressure fields for one strategic domain."""
    all_for_baseline = list(domain_alerts) + list(prev_alerts)
    if not domain_alerts:
        return {}

    latest = max(
        domain_alerts,
        key=lambda a: (raw_intensity_from_alert(a), _alert_ts(a)),
    )
    raw_current = raw_intensity_from_alert(latest)
    ui_current = ui_display_intensity(raw_current)
    baseline_raw = decayed_domain_baseline(all_for_baseline, now)
    baseline_ui = ui_display_intensity(baseline_raw)

    prev_peak_raw = max((raw_intensity_from_alert(a) for a in prev_alerts), default=0.0)
    ui_prev_peak = ui_display_intensity(prev_peak_raw)
    ui_delta = round(ui_current - ui_prev_peak, 1)

    badge = classify_pressure_badge(domain_alerts, now, ui_current=ui_current)

    out: dict[str, Any] = {
        "intensity": ui_current,
        "raw_intensity": round(raw_current, 2),
        "intensity_delta": ui_delta,
        "baseline_raw": round(baseline_raw, 2),
        "baseline_ui": round(baseline_ui, 2),
        "spike_detected": spike_vs_baseline(
            raw_current, baseline_raw, ui_delta=ui_delta
        ),
        "anomaly_detected": ui_current >= ANOMALY_UI_THRESHOLD,
        "anomaly_description": (
            f"Statistical outlier detected in momentum curves."
            if ui_current >= ANOMALY_UI_THRESHOLD
            else None
        ),
    }
    if badge:
        out.update(badge)
    return out
