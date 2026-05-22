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
