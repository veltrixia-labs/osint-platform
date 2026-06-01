"""
Fluid Dynamics — Choke-Point Flow Engine
========================================

Models the global logistics network as a fluid system where:

    viscosity   = OSINT alert intensity at the choke-point's topics
    physical_Q  = nominal daily throughput (mbpd or container-equivalent)

For each maritime node we compute a **flow restriction factor**:

    restriction = sigmoid( viscosity / max(physical_Q, ε) - baseline )

The restriction is then propagated to the node's downstream sectors via the
catalog's ``downstream_sectors`` list — that is the percentage drag the engine
expects each sector to feel until the choke-point clears.

No external deps — pure Python math.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AlertLog
from analysis.pro_domain_config import infer_domain_from_topic
from analysis.intensity_pressure import raw_intensity_from_alert, ui_display_intensity
from data_sources.eia_choke_point_catalog import get_choke_points

logger = logging.getLogger(__name__)

# Time window used to integrate OSINT viscosity. 24h matches the cluster window
# already used by every other Pro-grade engine.
CHOKE_WINDOW_HOURS = 24

# Viscosity is normalised against this baseline before the sigmoid runs, so a
# node with no recent alerts maps to restriction ≈ 0.05 (near-zero drag) and
# a node with intensity-saturated coverage maps to restriction ≈ 0.95.
_BASELINE_VISCOSITY = 6.0  # roughly "two medium alerts per day"


def _sigmoid(x: float) -> float:
    """Logistic squashing. Centred at 0, asymptotes at 0 and 1."""
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _node_viscosity(alerts: List[AlertLog], topics: List[str]) -> Dict[str, Any]:
    """
    Sum of UI-intensities of alerts whose domain is in `topics`. Returns both
    the raw viscosity total and the per-alert breakdown for explainability.
    """
    domain_set = set(topics)
    matching: List[Dict[str, Any]] = []
    total = 0.0
    peak = 0.0
    for a in alerts:
        domain = infer_domain_from_topic(a.topic or "")
        if domain not in domain_set:
            continue
        ui = ui_display_intensity(raw_intensity_from_alert(a))
        total += ui
        peak = max(peak, ui)
        matching.append({
            "alert_id": str(a.id),
            "topic": a.topic,
            "domain": domain,
            "intensity": round(ui, 2),
            "target_label": getattr(a, "target_label", None),
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
        })
    return {"total_viscosity": total, "peak_intensity": peak, "matched_alerts": matching}


def _restriction_from_viscosity(viscosity: float) -> float:
    """
    Map a viscosity total → [0,1] restriction factor.
    Centered on `_BASELINE_VISCOSITY`; sigmoid keeps it bounded.
    """
    x = (viscosity - _BASELINE_VISCOSITY) / max(_BASELINE_VISCOSITY, 1.0)
    return round(_sigmoid(x), 4)


def _downstream_drag(
    cp: Dict[str, Any],
    restriction: float,
) -> List[Dict[str, Any]]:
    """
    Project a node's restriction onto its downstream sectors. Drag scales with
    the choke-point's nominal physical throughput so Hormuz (21 mbpd) hits
    harder than Bosphorus (2.9 mbpd) at equal viscosity.
    """
    weight = float(cp.get("daily_volume_mbpd") or 1.0)
    weight_norm = min(1.0, weight / 21.0)  # Hormuz = 1.0 max
    drag = restriction * weight_norm
    return [
        {
            "sector": sector,
            "drag": round(drag, 4),
            "explanation": (
                f"{cp['label']} carries {weight:.1f} mbpd-equiv; "
                f"current OSINT viscosity → {int(round(restriction * 100))}% local "
                f"restriction × {int(round(weight_norm * 100))}% weight → "
                f"{int(round(drag * 100))}% downstream drag."
            ),
        }
        for sector in cp.get("downstream_sectors", [])
    ]


async def compute_choke_point_flow(
    db: AsyncSession,
    *,
    window_hours: int = CHOKE_WINDOW_HOURS,
) -> Dict[str, Any]:
    """
    Compute restriction + downstream drag for every maritime choke-point.

    Returns a payload ready for the choke-point map UI:
        {
          "nodes": [{id, label, lat, lng, restriction, viscosity, ...}, ...],
          "edges": [{from: <node_id>, to_sector: <sector>, drag: ...}],
          "global_restriction": float,
          ...
        }
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
        logger.warning("Choke-point alert fetch failed: %s", exc, exc_info=True)
        alerts = []

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    restrictions: List[float] = []

    for cp in get_choke_points():
        topic_match = _node_viscosity(alerts, cp.get("osint_topics") or [])
        restriction = _restriction_from_viscosity(topic_match["total_viscosity"])
        restrictions.append(restriction * float(cp.get("daily_volume_mbpd") or 0.0))

        node = {
            "id": cp["id"],
            "label": cp["label"],
            "lat": cp["lat"],
            "lng": cp["lng"],
            "daily_volume_mbpd": cp["daily_volume_mbpd"],
            "primary_commodity": cp.get("primary_commodity"),
            "description": cp.get("description"),
            "viscosity": round(topic_match["total_viscosity"], 2),
            "peak_intensity": round(topic_match["peak_intensity"], 2),
            "matched_alert_count": len(topic_match["matched_alerts"]),
            "matched_alerts": topic_match["matched_alerts"][:6],   # cap for payload size
            "restriction": restriction,
            "restriction_label": _restriction_label(restriction),
            "downstream_sectors": cp.get("downstream_sectors", []),
        }
        nodes.append(node)

        for drag_edge in _downstream_drag(cp, restriction):
            edges.append({
                "from_node": cp["id"],
                "from_label": cp["label"],
                **drag_edge,
            })

    # Aggregate: weight each node's restriction by its physical throughput
    total_throughput = sum(float(cp.get("daily_volume_mbpd") or 0.0) for cp in get_choke_points())
    global_restriction = (sum(restrictions) / total_throughput) if total_throughput > 0 else 0.0

    return {
        "nodes": nodes,
        "edges": edges,
        "global_restriction": round(global_restriction, 4),
        "global_restriction_label": _restriction_label(global_restriction),
        "window_hours": window_hours,
        "baseline_viscosity": _BASELINE_VISCOSITY,
        "generated_at": now.isoformat(),
    }


def _restriction_label(r: float) -> str:
    if r >= 0.75:
        return "Severe"
    if r >= 0.50:
        return "Elevated"
    if r >= 0.25:
        return "Moderate"
    return "Nominal"
