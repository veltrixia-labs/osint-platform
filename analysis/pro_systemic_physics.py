"""
Systemic Fragility Engine
=========================

Applies statistical mechanics (Shannon entropy) and fluid dynamics (kinematic
viscosity) to market / OSINT data in order to quantify how close the system is
to a *phase transition* — a regime break such as a crash, illiquidity event,
or supply-chain blockage.

Two orthogonal signals:

    1. **Network entropy** — Shannon entropy of the volatility distribution.
       High entropy means the system's volatility states are dispersed
       (no dominant regime), which is the classical pre-transition fingerprint.

    2. **Kinematic viscosity** — variance / flow ratio. High viscosity means
       the "fluid" (money or supply-chain goods) is choking: lots of stress
       per unit of throughput.

When BOTH signals exceed their critical thresholds, the engine raises a
``phase_transition_warning``. The thresholds are class-level constants so
they can be tuned without touching call sites.

No new external dependencies: numpy + pandas (already required project-wide).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Union

import numpy as np
import pandas as pd

Numeric = Union[int, float]
NumericSeries = Union[List[Numeric], "pd.Series", "np.ndarray", Iterable[Numeric]]


class SystemicFragilityEngine:
    """
    Stateless math engine. Construct once per request; methods are pure
    functions of their inputs.

    Critical thresholds are defined at class level so a downstream caller can
    introspect them (`SystemicFragilityEngine.ENTROPY_CRITICAL`) or pass
    overrides into `evaluate_critical_state` for back-testing.
    """

    #: Normalised Shannon entropy threshold (0..1) above which the volatility
    #: distribution is considered "maximally disordered" — the pre-transition
    #: fingerprint. Default 0.85 ≈ "top 15% of historical regimes".
    ENTROPY_CRITICAL: float = 0.85

    #: Kinematic viscosity threshold. Variance has the squared units of the
    #: input (typically %²), divided by per-window flow count. Default 0.10
    #: corresponds to "1% std × 1% std / 10-unit flow" — i.e. material stress
    #: per unit of throughput. Calibrated for ranges typical of the Pro
    #: pipeline's daily macro / market signals.
    VISCOSITY_CRITICAL: float = 0.10

    #: Histogram bin count for the entropy estimate. 10 bins on absolute
    #: volatility magnitudes is the standard institutional choice — enough
    #: granularity to separate calm vs. shock days without over-fitting.
    DEFAULT_BINS: int = 10

    def __init__(
        self,
        *,
        n_bins: int = DEFAULT_BINS,
        entropy_threshold: float = ENTROPY_CRITICAL,
        viscosity_threshold: float = VISCOSITY_CRITICAL,
    ) -> None:
        if n_bins < 2:
            raise ValueError("n_bins must be >= 2")
        self.n_bins = int(n_bins)
        self.entropy_threshold = float(entropy_threshold)
        self.viscosity_threshold = float(viscosity_threshold)

    # ─── 1. Shannon entropy ──────────────────────────────────────────────

    def calculate_network_entropy(self, volatility_series: NumericSeries) -> float:
        """
        Shannon entropy of the absolute-volatility histogram, normalised to
        ``[0, 1]`` so a uniform distribution maps to exactly 1.0 and a
        perfectly concentrated one maps to 0.0.

        Steps:
          1. Cast to a finite-only numpy array.
          2. Take absolute values (sign of volatility carries direction,
             but disorder is a function of magnitude only).
          3. Histogram into ``n_bins`` buckets.
          4. ``H = -Σ p_i ln(p_i)``  with the convention ``0·ln(0) = 0``.
          5. Normalise by ``ln(n_bins)`` (entropy of a uniform N-bucket dist.).

        Returns a float in ``[0, 1]``. Series with fewer than 2 valid points
        always return 0.0 — there is no defensible "disorder" estimate yet.
        """
        if volatility_series is None:
            return 0.0
        arr = np.asarray(list(volatility_series), dtype=float) \
            if not isinstance(volatility_series, (np.ndarray, pd.Series)) \
            else np.asarray(volatility_series, dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size < 2:
            return 0.0

        magnitudes = np.abs(arr)
        # If every observation is identical magnitude the histogram collapses
        # into a single bin — entropy is exactly 0.0 by construction.
        if np.all(magnitudes == magnitudes[0]):
            return 0.0

        hist, _ = np.histogram(magnitudes, bins=self.n_bins)
        total = hist.sum()
        if total <= 0:
            return 0.0
        p = hist / total
        nonzero = p[p > 0]
        h_nats = float(-np.sum(nonzero * np.log(nonzero)))
        h_max = math.log(self.n_bins)
        if h_max <= 0:
            return 0.0
        return float(np.clip(h_nats / h_max, 0.0, 1.0))

    # ─── 2. Kinematic viscosity ──────────────────────────────────────────

    def calculate_kinematic_viscosity(
        self,
        price_variance: Numeric,
        volume_flow: Numeric,
        *,
        flow_floor: float = 1.0,
    ) -> float:
        """
        Kinematic viscosity in the market analogy:

            ν = variance(price) / max(volume_flow, flow_floor)

        - High variance + low volume → "choked fluid" (illiquid stress).
        - Low variance + high volume → "free flow" (healthy market).

        ``flow_floor`` is a small positive number (default 1.0 — one "unit"
        of flow) that prevents division-by-zero AND caps the response when
        flow approaches zero. Without the floor a zero-flow window would
        return +inf, breaking downstream JSON serialisation.
        """
        variance = float(price_variance) if price_variance is not None else 0.0
        flow = float(volume_flow) if volume_flow is not None else 0.0
        if not math.isfinite(variance) or variance < 0:
            return 0.0
        if not math.isfinite(flow):
            flow = 0.0
        effective_flow = max(flow, max(flow_floor, 1e-9))
        return float(variance / effective_flow)

    # ─── 3. Criticality classifier ───────────────────────────────────────

    def evaluate_critical_state(
        self,
        entropy: float,
        viscosity: float,
        *,
        entropy_threshold: Optional[float] = None,
        viscosity_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Compose the two component scores into a single criticality verdict.

        ``phase_transition_warning`` fires when BOTH components are critical
        simultaneously — the conjunction rule prevents single-axis noise
        (e.g. a quiet but illiquid regime, or a noisy but well-flowing one)
        from raising false alarms.

        Returns a structured payload suitable for direct JSON serialisation:

            {
              "entropy_index": <float [0,1]>,
              "viscosity_coefficient": <float>,
              "entropy_critical": <bool>,
              "viscosity_critical": <bool>,
              "phase_transition_warning": <bool>,
              "entropy_threshold": <float>,
              "viscosity_threshold": <float>,
              "label": "PHASE TRANSITION IMMINENT" | "ENTROPY ELEVATED"
                       | "FLOW CHOKING" | "STABLE" | "INSUFFICIENT DATA",
              "rationale": <str>,
            }
        """
        e_thr = float(self.entropy_threshold if entropy_threshold is None else entropy_threshold)
        v_thr = float(self.viscosity_threshold if viscosity_threshold is None else viscosity_threshold)

        e = float(entropy)
        v = float(viscosity)

        entropy_critical = e > e_thr
        viscosity_critical = v > v_thr
        warning = entropy_critical and viscosity_critical

        # Honest empty-state — caller passed near-zero inputs (no data yet).
        if e <= 0.0 and v <= 0.0:
            label = "INSUFFICIENT DATA"
            rationale = (
                "Volatility series and flow are both empty — populate at "
                "least two macro/market observations to evaluate fragility."
            )
        elif warning:
            label = "PHASE TRANSITION IMMINENT"
            rationale = (
                f"Disorder index H={e:.3f} exceeds critical {e_thr:.2f} "
                f"AND kinematic viscosity ν={v:.3f} exceeds {v_thr:.2f} — "
                "the system is simultaneously dispersed and choking. "
                "Historical precedent: this conjunction precedes regime breaks."
            )
        elif entropy_critical:
            label = "ENTROPY ELEVATED"
            rationale = (
                f"Volatility states are dispersed (H={e:.3f} > {e_thr:.2f}) "
                "but flow is absorbing the stress; monitor for viscosity rise."
            )
        elif viscosity_critical:
            label = "FLOW CHOKING"
            rationale = (
                f"Kinematic viscosity ν={v:.3f} exceeds {v_thr:.2f} — "
                "flow is restricted relative to variance, but the regime is "
                "still concentrated. A burst of dispersion would trigger transition."
            )
        else:
            label = "STABLE"
            rationale = (
                f"Both components within tolerance (H={e:.3f}, ν={v:.3f}). "
                "Regime is concentrated and well-flowing — no transition signal."
            )

        return {
            "entropy_index": round(e, 4),
            "viscosity_coefficient": round(v, 4),
            "entropy_critical": entropy_critical,
            "viscosity_critical": viscosity_critical,
            "phase_transition_warning": warning,
            "entropy_threshold": e_thr,
            "viscosity_threshold": v_thr,
            "label": label,
            "rationale": rationale,
        }

    # ─── Convenience composer ───────────────────────────────────────────

    def analyse(
        self,
        volatility_series: NumericSeries,
        *,
        price_variance: Optional[Numeric] = None,
        volume_flow: Optional[Numeric] = None,
    ) -> Dict[str, Any]:
        """
        One-shot helper: run all three methods and return the merged payload.

        ``price_variance`` defaults to ``np.var(volatility_series)`` when the
        caller has not pre-computed it. ``volume_flow`` defaults to the count
        of finite observations in the series (a sensible "throughput" proxy
        when the caller has no separate flow signal).
        """
        if price_variance is None or volume_flow is None:
            arr = np.asarray(list(volatility_series), dtype=float) \
                if not isinstance(volatility_series, (np.ndarray, pd.Series)) \
                else np.asarray(volatility_series, dtype=float)
            arr = arr[np.isfinite(arr)]
            if price_variance is None:
                price_variance = float(np.var(arr)) if arr.size >= 2 else 0.0
            if volume_flow is None:
                volume_flow = float(arr.size)

        entropy = self.calculate_network_entropy(volatility_series)
        viscosity = self.calculate_kinematic_viscosity(price_variance, volume_flow)
        verdict = self.evaluate_critical_state(entropy, viscosity)
        verdict["price_variance"] = round(float(price_variance), 6)
        verdict["volume_flow"] = round(float(volume_flow), 4)
        verdict["sample_size"] = int(_finite_count(volatility_series))
        return verdict


def _finite_count(series: NumericSeries) -> int:
    if series is None:
        return 0
    arr = np.asarray(list(series), dtype=float) \
        if not isinstance(series, (np.ndarray, pd.Series)) \
        else np.asarray(series, dtype=float)
    return int(np.isfinite(arr).sum())
