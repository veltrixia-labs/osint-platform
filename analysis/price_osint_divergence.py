"""
Price-OSINT Divergence Engine (Hidden Accumulation)
===================================================

Detects structural divergence between OSINT alert intensity and the price of
the corresponding macro asset, then overlays CFTC commercial / non-commercial
positioning to identify *hidden accumulation* windows.

Strict guardrails reused from `analysis.pro_structural_compiler`:

    PRO_REPORT_CLUSTER_WINDOW_HOURS = 24
    PRO_REPORT_REIGNITE_FACTOR      = 1.5

These constants are imported — never overridden — so the divergence detector
operates on the exact same regime boundary as Lead-Lag, Pro Reports, and
alert dedup.

Detection logic (per (topic, macro_ticker) pair):

  1. Cluster current-window alerts (last 24h, suppressed=False).
  2. Compute peak intensity in the current cluster and the most-recent
     cluster before that (rolling baseline within the same window length).
  3. Require ``current_peak >= 1.5 × baseline_peak`` AND ``baseline_peak >= 1.0``
     so we don't fire on first-touch spikes from cold-start.
  4. Compute the macro asset's 24h price change. If price is **flat or up**
     while OSINT intensity surged, that is the divergence trigger.
  5. If COTReport data exists for the window, overlay commercial net position
     change to confirm institutional accumulation.

No external deps — uses pandas / numpy already in the project.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AlertLog, ExternalObservation, COTReport
from analysis.pro_structural_compiler import (
    PRO_REPORT_CLUSTER_WINDOW_HOURS,
    PRO_REPORT_REIGNITE_FACTOR,
)
from analysis.pro_domain_config import infer_domain_from_topic
from analysis.intensity_pressure import raw_intensity_from_alert, ui_display_intensity
from data_sources.fred_series_catalog import get_tradeable_macro_ids
from data_sources.cftc_series_catalog import get_cot_market_for_macro

logger = logging.getLogger(__name__)

# Re-export the strict thresholds so other modules can introspect what the
# engine is using (and tests can assert against them).
CLUSTER_WINDOW_HOURS: int = PRO_REPORT_CLUSTER_WINDOW_HOURS
REIGNITE_FACTOR: float = PRO_REPORT_REIGNITE_FACTOR

# Baseline floor: we never fire when the prior cluster's peak was below this,
# to avoid spurious "10x intensity jump" alerts from near-zero noise floors.
MIN_BASELINE_INTENSITY = 1.0

# Macro asset → strategic topic mapping. Mirrors the dynamic-selector
# allowlist; sourcing the macro side from this list keeps the divergence
# engine internally consistent with the Macro Transmission engine.
_MACRO_TO_TOPIC: Dict[str, str] = {
    "DCOILWTICO": "energy_resource_risk",
    "DGS10":      "global_market_intelligence",
    "VIXCLS":     "global_market_intelligence",
    "PCOPPUSDM":  "supply_chain_intelligence",
    "DTWEXBGS":   "global_market_intelligence",
}


async def _peak_intensity_window(
    db: AsyncSession, *,
    topic_domain: str,
    start: datetime,
    end: datetime,
) -> float:
    """Max UI-intensity in [start, end) for alerts whose domain == topic_domain."""
    stmt = (
        select(AlertLog)
        .where(
            and_(
                AlertLog.triggered_at >= start,
                AlertLog.triggered_at < end,
                AlertLog.suppressed == False,  # noqa: E712
            )
        )
    )
    rows = list((await db.execute(stmt)).scalars().all())
    peak = 0.0
    for a in rows:
        if infer_domain_from_topic(a.topic or "") != topic_domain:
            continue
        ui = ui_display_intensity(raw_intensity_from_alert(a))
        if ui > peak:
            peak = ui
    return peak


async def _macro_price_change(
    db: AsyncSession, *,
    macro_ticker: str,
    start: datetime,
    end: datetime,
) -> Optional[float]:
    """
    Percentage change of `macro_ticker` close prices between the last obs
    before `start` and the last obs at-or-before `end`. None if data missing.
    """
    base = (
        await db.execute(
            select(ExternalObservation)
            .where(
                ExternalObservation.series_id == macro_ticker,
                ExternalObservation.date <= start.date(),
            )
            .order_by(desc(ExternalObservation.date))
            .limit(1)
        )
    ).scalar_one_or_none()
    latest = (
        await db.execute(
            select(ExternalObservation)
            .where(
                ExternalObservation.series_id == macro_ticker,
                ExternalObservation.date <= end.date(),
            )
            .order_by(desc(ExternalObservation.date))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not base or not latest or base.value in (None, 0) or latest.value is None:
        return None
    return ((latest.value - base.value) / abs(base.value)) * 100.0


async def _cot_net_position_delta(
    db: AsyncSession, *,
    market_and_exchange: str,
    cluster_end: datetime,
) -> Optional[Dict[str, Any]]:
    """
    Pull the two most recent weekly COT rows on or before `cluster_end` and
    compute the change in **commercial** net position (commercials = the smart
    money for our hidden-accumulation thesis).
    """
    # `COTReport.report_date` is stored timezone-naive (CFTC publishes one
    # weekly snapshot date with no time component). Strip tzinfo from our
    # tz-aware comparison value so Postgres doesn't complain about mixing
    # offset-aware and offset-naive timestamps.
    cluster_end_naive = cluster_end.replace(tzinfo=None) if cluster_end.tzinfo else cluster_end
    stmt = (
        select(COTReport)
        .where(
            COTReport.market_and_exchange == market_and_exchange,
            COTReport.report_date <= cluster_end_naive,
        )
        .order_by(desc(COTReport.report_date))
        .limit(2)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if len(rows) < 2:
        return None
    latest, prior = rows[0], rows[1]
    comm_net_latest = (latest.comm_long or 0) - (latest.comm_short or 0)
    comm_net_prior = (prior.comm_long or 0) - (prior.comm_short or 0)
    delta = comm_net_latest - comm_net_prior
    return {
        "market": market_and_exchange,
        "latest_report_date": latest.report_date.isoformat() if latest.report_date else None,
        "comm_net_position_latest": comm_net_latest,
        "comm_net_position_prior": comm_net_prior,
        "comm_net_delta_contracts": delta,
        # Positive delta = commercials added to net long = accumulation
        "accumulation_direction": "buying" if delta > 0 else "selling" if delta < 0 else "flat",
    }


async def detect_hidden_accumulation(
    db: AsyncSession,
    *,
    cluster_window_hours: int = CLUSTER_WINDOW_HOURS,
    reignite_factor: float = REIGNITE_FACTOR,
    macro_tickers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Sweep every tradeable (macro_ticker, topic) pair and emit a list of
    divergence events that satisfy ALL guardrails:

        current_peak    ≥  reignite_factor × baseline_peak    (1.5x)
        baseline_peak   ≥  MIN_BASELINE_INTENSITY              (avoid noise)
        macro_24h_change ≥  0%                                 (price flat / up)
        cluster window  =  24h                                 (regime-aligned)

    When CFTC data is available, the commercial-net delta is overlaid as
    confirming evidence.
    """
    # Strict guardrails: never accept looser values than the Pro-grade floors.
    if cluster_window_hours < PRO_REPORT_CLUSTER_WINDOW_HOURS:
        logger.warning(
            "Divergence engine: cluster window %dh below Pro floor %dh — clamping.",
            cluster_window_hours, PRO_REPORT_CLUSTER_WINDOW_HOURS,
        )
        cluster_window_hours = PRO_REPORT_CLUSTER_WINDOW_HOURS
    if reignite_factor < PRO_REPORT_REIGNITE_FACTOR:
        logger.warning(
            "Divergence engine: reignite %.2fx below Pro floor %.2fx — clamping.",
            reignite_factor, PRO_REPORT_REIGNITE_FACTOR,
        )
        reignite_factor = PRO_REPORT_REIGNITE_FACTOR

    if macro_tickers is None:
        macro_tickers = [m for m in get_tradeable_macro_ids() if m in _MACRO_TO_TOPIC]

    now = datetime.now(timezone.utc)
    cluster_end = now
    cluster_start = now - timedelta(hours=cluster_window_hours)
    baseline_start = cluster_start - timedelta(hours=cluster_window_hours)

    findings: List[Dict[str, Any]] = []
    inspected: List[Dict[str, Any]] = []

    for ticker in macro_tickers:
        topic = _MACRO_TO_TOPIC.get(ticker)
        if not topic:
            continue

        current_peak = await _peak_intensity_window(
            db, topic_domain=topic, start=cluster_start, end=cluster_end,
        )
        baseline_peak = await _peak_intensity_window(
            db, topic_domain=topic, start=baseline_start, end=cluster_start,
        )
        price_change_pct = await _macro_price_change(
            db, macro_ticker=ticker, start=baseline_start, end=cluster_end,
        )

        inspection_row = {
            "macro_ticker": ticker,
            "topic": topic,
            "current_peak_intensity": round(current_peak, 2),
            "baseline_peak_intensity": round(baseline_peak, 2),
            "price_change_pct_24h": (
                None if price_change_pct is None else round(price_change_pct, 3)
            ),
        }
        inspected.append(inspection_row)

        # --- Gate 1: baseline must be above the noise floor ----------------
        if baseline_peak < MIN_BASELINE_INTENSITY:
            continue
        # --- Gate 2: current must clear 1.5x of baseline -------------------
        intensity_ratio = current_peak / baseline_peak if baseline_peak > 0 else 0.0
        if intensity_ratio < reignite_factor:
            continue
        # --- Gate 3: price must NOT have dropped --------------------------
        if price_change_pct is None or price_change_pct < 0.0:
            continue

        cot_market = get_cot_market_for_macro(ticker)
        cot_overlay = None
        if cot_market:
            cot_overlay = await _cot_net_position_delta(
                db,
                market_and_exchange=cot_market["market_and_exchange"],
                cluster_end=cluster_end,
            )

        findings.append({
            "macro_ticker": ticker,
            "topic": topic,
            "intensity_ratio": round(intensity_ratio, 3),
            "current_peak_intensity": round(current_peak, 2),
            "baseline_peak_intensity": round(baseline_peak, 2),
            "price_change_pct_24h": round(price_change_pct, 3),
            "cot_overlay": cot_overlay,
            "verdict": _classify_divergence(intensity_ratio, price_change_pct, cot_overlay),
            "window_start": cluster_start.isoformat(),
            "window_end": cluster_end.isoformat(),
        })

    return {
        "findings": findings,
        "inspected_pairs": inspected,
        "cluster_window_hours": cluster_window_hours,
        "reignite_factor": reignite_factor,
        "min_baseline_intensity": MIN_BASELINE_INTENSITY,
        "generated_at": now.isoformat(),
    }


def _classify_divergence(
    intensity_ratio: float,
    price_change_pct: float,
    cot_overlay: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Produce a UI-ready label for the divergence row:
      • "Confirmed Accumulation" — COT shows commercials buying
      • "Suspected Accumulation" — divergence but no COT to confirm
      • "Sentiment Decoupling"  — divergence with COT selling (retail-driven)
    """
    if cot_overlay is None:
        return {
            "label": "Suspected Accumulation",
            "emoji": "🕯️",
            "accent_color": "#fbbf24",
            "rationale": (
                f"OSINT intensity +{intensity_ratio:.2f}x within 24h while price "
                f"moved {price_change_pct:+.2f}%. No CFTC overlay available."
            ),
        }
    direction = cot_overlay.get("accumulation_direction")
    delta = cot_overlay.get("comm_net_delta_contracts") or 0
    if direction == "buying":
        return {
            "label": "Confirmed Accumulation",
            "emoji": "🔒",
            "accent_color": "#10b981",
            "rationale": (
                f"OSINT intensity +{intensity_ratio:.2f}x while price stayed "
                f"{price_change_pct:+.2f}% — and CFTC commercials added "
                f"{delta:+,} net contracts. Smart money is accumulating."
            ),
        }
    if direction == "selling":
        return {
            "label": "Sentiment Decoupling",
            "emoji": "⚡",
            "accent_color": "#f87171",
            "rationale": (
                f"OSINT intensity surged +{intensity_ratio:.2f}x but CFTC "
                f"commercials cut {delta:+,} net contracts. Retail noise without "
                f"institutional follow-through."
            ),
        }
    return {
        "label": "Suspected Accumulation",
        "emoji": "🕯️",
        "accent_color": "#fbbf24",
        "rationale": (
            f"OSINT intensity +{intensity_ratio:.2f}x, price {price_change_pct:+.2f}%, "
            f"CFTC positioning flat."
        ),
    }
