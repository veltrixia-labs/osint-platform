"""Tests for asymptotic UI scaling and pressure badge timing."""
from datetime import datetime, timezone, timedelta

from analysis.intensity_pressure import (
    REIGNITE_RAW_FACTOR,
    ui_display_intensity,
    spike_vs_baseline,
    classify_pressure_badge,
)


class _FakeAlert:
    def __init__(self, raw: float, hours_ago: float):
        self.intensity = raw
        self.metadata_json = {"raw_intensity": raw}
        self.triggered_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)


def test_ui_never_hard_caps_at_ten():
    assert ui_display_intensity(10) < 10.0
    assert ui_display_intensity(30) > ui_display_intensity(10)
    assert ui_display_intensity(50) > ui_display_intensity(30)


def test_spike_uses_raw_reignite_factor():
    assert spike_vs_baseline(15.0, 10.0, ui_delta=0.5, reignite_factor=REIGNITE_RAW_FACTOR)


def test_badge_transitions_to_sustained_after_four_hours():
    now = datetime.now(timezone.utc)
    alerts = [_FakeAlert(12.0, 5.0), _FakeAlert(14.0, 0.5)]
    badge = classify_pressure_badge(alerts, now, ui_current=ui_display_intensity(14.0))
    assert badge is not None
    assert badge["pressure_badge_variant"] == "sustained"
