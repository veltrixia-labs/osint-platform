import math
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from db.models import ExternalObservation, AlertLog


from processor.topic_registry import normalize_canonical_topic
from data_sources.fred_series_catalog import (
    get_tradeable_macro_ids,
    is_monthly_series,
)

logger = logging.getLogger(__name__)

# Intensity values below this floor are clamped when used as the denominator
# of a percentage change, so that a jump from ~0 to a meaningful intensity
# does not produce an explosive (or infinite) RoC that drowns out real signal.
_INTENSITY_DENOMINATOR_FLOOR = 1.0

# When a monthly series is selected, the default 7-day RoC window collapses
# onto repeated forward-filled values. Expand to ~30 days so the rate-of-change
# window spans a real observation gap.
_MONTHLY_ROC_WINDOW_DAYS = 30
_MONTHLY_LOOKBACK_DAYS = 365  # 12+ observations for stable CCF on monthly data


class UnknownMacroSeriesError(ValueError):
    """Raised when `macro_series_id` is not in the tradeable allowlist."""


class MacroTransmissionEngine:
    """
    Quantitative engine to measure the transmission lag and beta correlation
    between macro indicators (like WTI Crude Oil) and specific sector risk intensity.
    """
    def __init__(self, db: AsyncSession):
        self.db = db

    async def compute_transmission_metrics(
        self,
        macro_series_id: str,
        target_topic: str,
        days_lookback: int = 90,
        roc_window: int = 7,
        include_inverse: bool = False,
    ) -> Dict[str, Any]:
        """
        Calculate CCF (Cross-Correlation Function) and Beta between a macro series and an alert topic.

        Resolution auto-adjustment: when ``macro_series_id`` is a monthly series
        (per the FRED catalog), the lookback and RoC window are automatically
        widened so the CCF operates on real observation deltas rather than
        forward-filled plateaus. This keeps the math valid for indicators like
        copper that only publish monthly.

        Allowlist: ``macro_series_id`` must be present in
        ``get_tradeable_macro_ids()``. Unknown tickers raise
        :class:`UnknownMacroSeriesError` so the API layer can surface a clean 400.

        When ``include_inverse`` is True the lag scan covers negative lags too,
        capturing regimes where alert intensity leads the macro asset (e.g.
        markets repricing *after* a geopolitical shock).
        """
        allowlist = get_tradeable_macro_ids()
        if macro_series_id not in allowlist:
            raise UnknownMacroSeriesError(
                f"Macro series '{macro_series_id}' is not registered as a "
                f"tradeable indicator. Allowed: {allowlist}"
            )

        if is_monthly_series(macro_series_id):
            # Bump both the lookback and the RoC window so we have at least
            # ~12 observations and a 1-month rate of change. Inputs greater
            # than the auto values are respected (caller can still ask for
            # more history); smaller values get raised to the auto floor.
            original_roc = roc_window
            original_lookback = days_lookback
            roc_window = max(roc_window, _MONTHLY_ROC_WINDOW_DAYS)
            days_lookback = max(days_lookback, _MONTHLY_LOOKBACK_DAYS)
            logger.info(
                "Macro series %s is monthly: roc_window %d->%d, lookback %d->%d",
                macro_series_id, original_roc, roc_window,
                original_lookback, days_lookback,
            )

        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=days_lookback)

        canonical_topic = normalize_canonical_topic(target_topic)

        # 1. Fetch Macro Series (e.g., DCOILWTICO)
        stmt_macro = select(ExternalObservation.date, ExternalObservation.value).where(
            and_(
                ExternalObservation.series_id == macro_series_id,
                ExternalObservation.date >= start_date.date()
            )
        ).order_by(ExternalObservation.date.asc())

        res_macro = await self.db.execute(stmt_macro)
        macro_data = res_macro.all()

        if not macro_data:
            return self._empty_result(
                macro_series_id, target_topic,
                roc_window=roc_window, days_lookback=days_lookback,
            )

        df_macro = pd.DataFrame(macro_data, columns=["date", "macro_value"])
        df_macro["date"] = pd.to_datetime(df_macro["date"])
        df_macro.set_index("date", inplace=True)
        # Forward-fill missing days (e.g. weekends for WTI): the last observed
        # price is the best estimate while the market is closed.
        df_macro = df_macro.resample("D").ffill().dropna()

        # Macro RoC: log return. Symmetric, additive over time, and free of
        # the inf risk that pct_change carries when a base value is near zero.
        macro_values = df_macro["macro_value"].clip(lower=1e-9)
        df_macro["macro_roc"] = np.log(macro_values).diff(roc_window)
        df_macro = df_macro.dropna()

        # 2. Fetch Alert Intensity for Target Topic
        stmt_alert = select(AlertLog.triggered_at, AlertLog.intensity).where(
            and_(
                AlertLog.topic == canonical_topic,
                AlertLog.triggered_at >= start_date
            )
        ).order_by(AlertLog.triggered_at.asc())

        res_alert = await self.db.execute(stmt_alert)
        alert_data = res_alert.all()

        if not alert_data:
            return self._empty_result(
                macro_series_id, target_topic, df_macro,
                roc_window=roc_window, days_lookback=days_lookback,
            )

        df_alert = pd.DataFrame(alert_data, columns=["date", "intensity"])
        df_alert["date"] = pd.to_datetime(df_alert["date"]).dt.tz_localize(None).dt.normalize()
        # Daily max intensity, sorted, with missing days zero-filled. We
        # deliberately avoid ffill here: an alert on day N should NOT carry
        # its intensity into days N+1, N+2, ... — that previously produced an
        # artificial high-intensity plateau and biased the RoC calculation.
        df_alert = df_alert.groupby("date")["intensity"].max().to_frame().sort_index()
        df_alert = df_alert.asfreq("D").fillna(0.0)

        # Intensity RoC: floored ratio. Numerator is the raw N-day change;
        # the denominator is clamped to `_INTENSITY_DENOMINATOR_FLOOR`, so a
        # jump from 0 → 5 becomes a finite +5.0 (500% above floor) instead of
        # +inf, while normal high-baseline changes are unaffected.
        prev_intensity = df_alert["intensity"].shift(roc_window)
        floored_denominator = prev_intensity.where(
            prev_intensity > _INTENSITY_DENOMINATOR_FLOOR,
            _INTENSITY_DENOMINATOR_FLOOR,
        )
        df_alert["intensity_roc"] = (
            df_alert["intensity"] - prev_intensity
        ) / floored_denominator
        df_alert = df_alert.replace([np.inf, -np.inf], np.nan).dropna()

        # 3. Align the two series for calculation
        df_calc = df_macro.join(df_alert, how="inner").dropna()

        if len(df_calc) < roc_window * 2:
            return self._empty_result(
                macro_series_id, target_topic, df_macro,
                roc_window=roc_window, days_lookback=days_lookback,
            )

        macro_signal = df_calc["macro_roc"].values
        target_signal = df_calc["intensity_roc"].values

        # 4. Cross-Correlation Function (CCF)
        # Normalize signals for correlation
        macro_norm = (macro_signal - np.mean(macro_signal)) / (np.std(macro_signal) + 1e-9)
        target_norm = (target_signal - np.mean(target_signal)) / (np.std(target_signal) + 1e-9)

        ccf = np.correlate(target_norm, macro_norm, mode="full")
        max_lag = min(14, len(macro_norm) - 1)
        center = len(macro_norm) - 1

        if include_inverse:
            # Symmetric scan: +lag = macro leads target, -lag = target leads macro.
            lags = np.arange(-max_lag, max_lag + 1)
            ccf_window = ccf[center - max_lag : center + max_lag + 1] / len(macro_norm)
        else:
            # Default: positive lags only (macro leads target).
            lags = np.arange(0, max_lag + 1)
            ccf_window = ccf[center : center + max_lag + 1] / len(macro_norm)

        peak_idx = int(np.argmax(np.abs(ccf_window)))
        peak_lag = int(lags[peak_idx])
        # Pearson correlation is bounded to [-1, 1]; clip defensively in case
        # floating-point error or unequal effective series lengths push the
        # normalised CCF slightly outside that range.
        peak_corr = float(np.clip(ccf_window[peak_idx], -1.0, 1.0))

        # 5. Calculate Beta (Sensitivity) at the aligned lag.
        if peak_lag > 0:
            # Macro leads target by `peak_lag` days.
            aligned_macro = macro_signal[:-peak_lag]
            aligned_target = target_signal[peak_lag:]
        elif peak_lag < 0:
            # Target leads macro by |peak_lag| days.
            shift = -peak_lag
            aligned_macro = macro_signal[shift:]
            aligned_target = target_signal[:-shift]
        else:
            aligned_macro = macro_signal
            aligned_target = target_signal

        if len(aligned_macro) >= 2 and np.var(aligned_macro) > 1e-9:
            beta = np.cov(aligned_macro, aligned_target)[0, 1] / np.var(aligned_macro)
        else:
            beta = 0.0
            
        # Format series for frontend (Using LEFT JOIN to always show WTI data)
        df_full = df_macro.join(df_alert[["intensity"]], how="left")
        df_full["intensity"] = df_full["intensity"].fillna(0.0)
        df_full.reset_index(inplace=True)
        
        series_data = []
        for _, row in df_full.iterrows():
            series_data.append({
                "date": row["date"].strftime("%Y-%m-%d"),
                "macro_value": float(row["macro_value"]),
                "intensity": float(row["intensity"])
            })
            
        return {
            "source": macro_series_id,
            "target": target_topic,
            "lag_days": peak_lag,
            "correlation": peak_corr,
            "beta": float(beta),
            "series": series_data,
            "resolution": "monthly" if is_monthly_series(macro_series_id) else "daily",
            "roc_window_days": int(roc_window),
            "days_lookback": int(days_lookback),
        }

    async def compute_correlation_matrix(
        self,
        days_lookback: int = 90,
        roc_window: int = 7,
        topics: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Fast cross-sectional correlation matrix for the Macro Influence Heatmap.

        Computes Pearson correlation of N-day log-returns (macro) vs floored RoC
        (alert intensity) for every (tradeable_macro × topic) pair using exactly
        TWO database queries — one batched macro fetch and one batched alert
        fetch — regardless of how many pairs are requested.

        Returns:
            {
                "macros":   [<MacroOption-like>],     # rows
                "topics":   [<TopicOption-like>],     # cols
                "cells":    [[{correlation, lag_days, sample_size, ...}, ...]],
                "generated_at": <iso8601>,
                "lookback_days": int,
                "roc_window_days": int,
            }
        """
        macros = get_tradeable_macro_ids()
        if topics is None:
            topics = [
                "energy_resource_risk", "global_market_intelligence",
                "ai_semiconductor_intelligence", "supply_chain_intelligence",
                "defense_technology", "crypto_geopolitics",
            ]
        canonical_topics = [normalize_canonical_topic(t) for t in topics]
        topic_canonical_map = dict(zip(topics, canonical_topics))

        now = datetime.now(timezone.utc)
        # Use the broader (monthly-friendly) lookback when any monthly series
        # is in the matrix — copper would otherwise have too few points.
        effective_lookback = days_lookback
        effective_roc = roc_window
        if any(is_monthly_series(m) for m in macros):
            effective_lookback = max(effective_lookback, _MONTHLY_LOOKBACK_DAYS)
            effective_roc = max(effective_roc, _MONTHLY_ROC_WINDOW_DAYS)
        start_date = now - timedelta(days=effective_lookback)

        # --- ONE batched macro query for all series at once -----------------
        stmt_macro = (
            select(
                ExternalObservation.series_id,
                ExternalObservation.date,
                ExternalObservation.value,
            )
            .where(
                and_(
                    ExternalObservation.series_id.in_(macros),
                    ExternalObservation.date >= start_date.date(),
                )
            )
            .order_by(ExternalObservation.series_id, ExternalObservation.date.asc())
        )
        macro_rows = (await self.db.execute(stmt_macro)).all()
        df_macro_long = pd.DataFrame(macro_rows, columns=["series_id", "date", "value"])

        # --- ONE batched alert query for all topics at once -----------------
        stmt_alert = (
            select(
                AlertLog.topic,
                AlertLog.triggered_at,
                AlertLog.intensity,
            )
            .where(
                and_(
                    AlertLog.topic.in_(canonical_topics),
                    AlertLog.triggered_at >= start_date,
                )
            )
        )
        alert_rows = (await self.db.execute(stmt_alert)).all()
        df_alert_long = pd.DataFrame(alert_rows, columns=["topic", "triggered_at", "intensity"])

        cells: List[List[Dict[str, Any]]] = []
        for macro_id in macros:
            row_cells: List[Dict[str, Any]] = []
            df_m = df_macro_long[df_macro_long["series_id"] == macro_id].copy()
            if df_m.empty:
                for t in topics:
                    row_cells.append(self._null_cell(macro_id, t, reason="no_macro_data"))
                cells.append(row_cells)
                continue

            df_m["date"] = pd.to_datetime(df_m["date"])
            df_m = df_m.set_index("date").sort_index()
            df_m = df_m[["value"]].rename(columns={"value": "macro_value"})
            df_m = df_m.resample("D").ffill().dropna()
            df_m["macro_roc"] = np.log(df_m["macro_value"].clip(lower=1e-9)).diff(effective_roc)
            df_m = df_m.dropna()

            for t in topics:
                canon = topic_canonical_map[t]
                df_a = df_alert_long[df_alert_long["topic"] == canon].copy()
                if df_a.empty:
                    row_cells.append(self._null_cell(macro_id, t, reason="no_alerts"))
                    continue

                df_a["date"] = pd.to_datetime(df_a["triggered_at"]).dt.tz_localize(None).dt.normalize()
                df_a = df_a.groupby("date")["intensity"].max().to_frame().sort_index()
                df_a = df_a.asfreq("D").fillna(0.0)
                prev = df_a["intensity"].shift(effective_roc)
                floored = prev.where(prev > _INTENSITY_DENOMINATOR_FLOOR, _INTENSITY_DENOMINATOR_FLOOR)
                df_a["intensity_roc"] = (df_a["intensity"] - prev) / floored
                df_a = df_a.replace([np.inf, -np.inf], np.nan).dropna()

                df_calc = df_m.join(df_a, how="inner").dropna()
                if len(df_calc) < effective_roc * 2:
                    row_cells.append(self._null_cell(macro_id, t, reason="insufficient_overlap"))
                    continue

                m_sig = df_calc["macro_roc"].values
                a_sig = df_calc["intensity_roc"].values
                m_norm = (m_sig - np.mean(m_sig)) / (np.std(m_sig) + 1e-9)
                a_norm = (a_sig - np.mean(a_sig)) / (np.std(a_sig) + 1e-9)
                ccf = np.correlate(a_norm, m_norm, mode="full")
                max_lag = min(7, len(m_norm) - 1)
                center = len(m_norm) - 1
                window = ccf[center : center + max_lag + 1] / len(m_norm)
                peak_idx = int(np.argmax(np.abs(window)))
                peak_corr = float(np.clip(window[peak_idx], -1.0, 1.0))

                row_cells.append({
                    "macro_id": macro_id,
                    "topic_id": t,
                    "correlation": round(peak_corr, 3),
                    "lag_days": int(peak_idx),
                    "sample_size": int(len(df_calc)),
                    "status": "ok",
                })
            cells.append(row_cells)

        return {
            "macros": macros,
            "topics": topics,
            "cells": cells,
            "generated_at": now.isoformat(),
            "lookback_days": int(effective_lookback),
            "roc_window_days": int(effective_roc),
        }

    @staticmethod
    def _null_cell(macro_id: str, topic_id: str, *, reason: str) -> Dict[str, Any]:
        return {
            "macro_id": macro_id,
            "topic_id": topic_id,
            "correlation": None,
            "lag_days": None,
            "sample_size": 0,
            "status": reason,
        }

    def _empty_result(
        self,
        macro_series_id: str,
        target_topic: str,
        df_macro: Optional[pd.DataFrame] = None,
        roc_window: int = 7,
        days_lookback: int = 90,
    ) -> Dict[str, Any]:
        series_data = []
        if df_macro is not None and not df_macro.empty:
            df_full = df_macro.copy()
            df_full.reset_index(inplace=True)
            for _, row in df_full.iterrows():
                series_data.append({
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "macro_value": float(row["macro_value"]),
                    "intensity": 0.0
                })
        return {
            "source": macro_series_id,
            "target": target_topic,
            "lag_days": 0,
            "correlation": 0.0,
            "beta": 0.0,
            "series": series_data,
            "resolution": "monthly" if is_monthly_series(macro_series_id) else "daily",
            "roc_window_days": int(roc_window),
            "days_lookback": int(days_lookback),
        }
