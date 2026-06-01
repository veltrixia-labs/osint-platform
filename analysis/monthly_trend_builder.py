"""
Monthly Trend Flow — extraction + flow aggregation.

Builds one month's flow/network snapshot from the Alert Stream:

  1. Pull every (non-suppressed) AlertLog in the calendar month. Alerts are
     already 24h-cluster-deduped at creation (jobs/alert_manager.py), so this is
     a straight time-window read.
  2. STRICT 1.5x spike filter, evaluated PER STRATEGIC DOMAIN (independent
     populations): keep an alert only when its raw intensity is >= 1.5x the
     decayed baseline of *its own* strategic domain at that moment. The baseline
     denominator is the domain's own prior population — so a Defense or Crypto
     surge is judged against Defense/Crypto history, never crowded out by
     high-volume Energy/Markets noise. No severity OR-clause.
  3. Bucket spiked alerts into the 6 canonical STRATEGIC_DOMAINS and (where
     coordinates resolve) route them through SpatialPhysicsEngine for entropy /
     viscosity / epicenter metrics, using the domain's omni geography.
  4. Serialise to a JSONB-ready snapshot. summary.domains ALWAYS contains all 6
     core domains (spiked/total counts + per-domain source_alert_ids provenance)
     so the UI evidence modal and the 6-node orbit can link to the raw alerts.

Pure aggregation: no DB writes here (the worker persists the result).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AlertLog
from analysis.intensity_pressure import raw_intensity_from_alert, decayed_domain_baseline
from analysis.pro_domain_config import infer_domain_from_topic, STRATEGIC_DOMAINS
from analysis.spatial_physics_engine import (
    DOMAIN_SITE_KEYS,
    GEO_REGISTRY,
    SpatialPhysicsEngine,
    ComputedSpatialNode,
    ComputedSpatialEdge,
    omni_domain_for_pro_domain,
)
from jobs.omni_spatial_worker import resolve_alert_coordinates

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "monthly_trend_v2"  # v2: per-strategic-domain independent spikes, all 6 domains
SPIKE_RATIO = 1.5  # strict raw-intensity reignite ratio (mirrors _PRO_MIN_REIGNITE_FACTOR)
# Month window spans ~30 days; the physics engine's window_hours only scales a few
# density proxies, so a 30-day window keeps the cluster-density math sane.
_MONTH_WINDOW_HOURS = 24.0 * 31

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# Human-facing sector label per STRATEGIC domain id (the canonical 6).
_DOMAIN_LABEL = {
    "energy_resource_risk": "Energy",
    "global_market_intelligence": "Markets",
    "crypto_geopolitics": "Crypto",
    "ai_semiconductor_intelligence": "AI / Semi",
    "defense_technology": "Defense",
    "supply_chain_intelligence": "Supply Chain",
}


def month_bounds(year: int, month: int) -> Tuple[datetime, datetime, str]:
    """Return (start_utc, end_utc, label) for a calendar month, end-exclusive."""
    if not (1 <= month <= 12):
        raise ValueError(f"month must be 1-12, got {month}")
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    label = f"{_MONTH_NAMES[month - 1]} {year}"
    return start, end, label


def _strict_spike(raw_current: float, baseline_raw: float) -> bool:
    """STRICT 1.5x raw-ratio spike (no UI-delta fallback)."""
    return baseline_raw > 0 and raw_current >= SPIKE_RATIO * baseline_raw


def _node_payload(n: ComputedSpatialNode, domain_id: str, source_alert_ids: List[str]) -> Dict[str, Any]:
    return {
        "id": f"{domain_id}__{n.site_key}",
        "domain_id": domain_id,
        "site_key": n.site_key,
        "name": n.name,
        "lat": round(float(n.lat), 5),
        "lon": round(float(n.lon), 5),
        "impact_score": round(float(n.impact_score), 2),
        "entropy_index": round(float(n.entropy_index), 4),
        "viscosity_coefficient": round(float(n.viscosity_coefficient), 4),
        "type": "epicenter" if n.is_epicenter else "affected",
        "event_count": int(n.event_count),
        "source_alert_ids": source_alert_ids,
    }


def _edge_payload(
    e: ComputedSpatialEdge,
    domain_id: str,
    coord_to_id: Dict[Tuple[float, float], str],
    prov_by_node: Dict[str, List[str]],
) -> Dict[str, Any]:
    src_id = coord_to_id.get((round(e.source_lat, 5), round(e.source_lon, 5)))
    tgt_id = coord_to_id.get((round(e.target_lat, 5), round(e.target_lon, 5)))
    # Edge provenance = union of its endpoint nodes' alerts (curated topology
    # edges aren't themselves alert-derived, but their endpoints are).
    src_ids = prov_by_node.get(src_id or "", [])
    tgt_ids = prov_by_node.get(tgt_id or "", [])
    union_ids = list(dict.fromkeys([*src_ids, *tgt_ids]))
    return {
        "domain_id": domain_id,
        "source_id": src_id,
        "target_id": tgt_id,
        "source_lon": round(float(e.source_lon), 5),
        "source_lat": round(float(e.source_lat), 5),
        "target_lon": round(float(e.target_lon), 5),
        "target_lat": round(float(e.target_lat), 5),
        "intensity": round(float(e.edge_intensity), 4),
        "edge_intensity": round(float(e.edge_intensity), 4),
        "viscosity_coefficient": round(float(e.viscosity_coefficient), 4),
        "order_level": int(e.order_level),
        "target_order": int(e.order_level),
        "source_alert_ids": union_ids,
    }


async def build_monthly_trend_snapshot(
    session: AsyncSession, year: int, month: int
) -> Dict[str, Any]:
    """Compute the flow snapshot dict for a calendar month (no DB writes)."""
    start, end, label = month_bounds(year, month)

    rows = (
        await session.execute(
            select(AlertLog)
            .where(
                AlertLog.triggered_at >= start,
                AlertLog.triggered_at < end,
                AlertLog.suppressed.is_(False),
            )
            .order_by(AlertLog.triggered_at.asc())
        )
    ).scalars().all()
    total = len(rows)

    # Offline geocoder (text → lat/lon) is optional; fall back to row coords.
    geo = None
    try:
        from analysis.pro_geo_locator import GeoLocator
        geo = GeoLocator()
    except Exception as exc:  # FileNotFoundError when geo DB absent, etc.
        logger.info("monthly_trend: GeoLocator unavailable (%s); using row coordinates only.", exc)

    engine = SpatialPhysicsEngine(window_hours=_MONTH_WINDOW_HOURS)

    # Per-STRATEGIC-domain independent populations (the 6 canonical domains).
    prior_by_domain: Dict[str, list] = defaultdict(list)       # baseline pool (prior activity)
    spiked_ids_by_domain: Dict[str, List[str]] = defaultdict(list)  # ALL spikes, time-ordered
    events_by_domain: Dict[str, list] = defaultdict(list)      # mappable spikes → spatial events
    total_by_domain: Dict[str, int] = defaultdict(int)
    # (strategic_domain, site_key) -> [alert_id]
    provenance: Dict[Tuple[str, str], List[str]] = defaultdict(list)

    for alert in rows:
        # Pass the headline so the sports/entertainment guardrail can intercept
        # items (e.g. World Cup) before macro keyword collisions misroute them.
        meta = alert.metadata_json if isinstance(alert.metadata_json, dict) else {}
        alert_text = f"{alert.target_label or ''} {meta.get('display_title', '')}"
        domain = infer_domain_from_topic(alert.topic or "", text=alert_text)
        total_by_domain[domain] += 1
        raw = raw_intensity_from_alert(alert)
        # STRICT 1.5x vs the domain's OWN prior population (independent baseline).
        baseline = decayed_domain_baseline(prior_by_domain[domain], now=alert.triggered_at)
        prior_by_domain[domain].append(alert)  # baseline = strictly prior activity
        if not _strict_spike(raw, baseline):
            continue

        spiked_ids_by_domain[domain].append(str(alert.id))

        # Spatial enrichment is best-effort: spikes without coordinates still
        # count toward the domain (news list / orbit), just not the geo metrics.
        coords = resolve_alert_coordinates(alert, geo) if geo else None
        lat = lon = None
        label_txt = ""
        if coords:
            lat, lon, label_txt = coords
        ev = engine.normalize_alert(
            alert, pro_domain_id=domain, lat=lat, lon=lon, label=label_txt
        )
        if not ev:
            continue
        omni = omni_domain_for_pro_domain(domain)
        allowed = DOMAIN_SITE_KEYS.get(omni, tuple(GEO_REGISTRY.keys()))
        site = engine.assign_site_key(ev, allowed)
        provenance[(domain, site)].append(str(alert.id))
        events_by_domain[domain].append(ev)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    entropies: List[float] = []
    viscosities: List[float] = []
    domain_summary: Dict[str, Any] = {}
    spiked_total = 0

    # ALWAYS iterate all 6 strategic domains so the snapshot is structurally
    # complete (the 6-node orbit renders every core domain, quiet or not).
    for domain in STRATEGIC_DOMAINS:
        spiked_ids = spiked_ids_by_domain.get(domain, [])
        spiked_total += len(spiked_ids)
        evs = events_by_domain.get(domain, [])
        epicenter_name = None
        node_ct = 0

        if evs:
            # Geo metrics use the domain's omni geography (site keys / topology).
            omni = omni_domain_for_pro_domain(domain)
            graph = engine.build_domain_graph(omni, evs)
            if graph.nodes:
                coord_to_id: Dict[Tuple[float, float], str] = {}
                prov_by_node: Dict[str, List[str]] = {}
                for n in graph.nodes:
                    node_id = f"{domain}__{n.site_key}"
                    alert_ids = provenance.get((domain, n.site_key), [])
                    nodes.append(_node_payload(n, domain, alert_ids))
                    coord_to_id[(round(float(n.lat), 5), round(float(n.lon), 5))] = node_id
                    prov_by_node[node_id] = alert_ids
                    if n.is_epicenter:
                        epicenter_name = n.name
                for e in graph.edges:
                    edges.append(_edge_payload(e, domain, coord_to_id, prov_by_node))
                entropies.append(graph.mean_entropy)
                viscosities.append(graph.mean_viscosity)
                node_ct = len(graph.nodes)

        domain_summary[domain] = {
            "domain_id": domain,
            "label": _DOMAIN_LABEL.get(domain, domain),
            "spiked": len(spiked_ids),
            "total": total_by_domain.get(domain, 0),
            "nodes": node_ct,
            "epicenter": epicenter_name,
            "source_alert_ids": spiked_ids,
        }

    # Rank only domains that actually spiked (quiet domains stay out of the headline).
    top_sectors = [
        d for d, v in sorted(domain_summary.items(), key=lambda kv: kv[1]["spiked"], reverse=True)
        if v["spiked"] > 0
    ]

    summary = {
        "alerts_total": total,
        "alerts_spiked": spiked_total,
        "entropy_index": round(sum(entropies) / len(entropies), 4) if entropies else 0.0,
        "viscosity_coefficient": round(sum(viscosities) / len(viscosities), 4) if viscosities else 0.0,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "spike_ratio": SPIKE_RATIO,
        "top_sectors": top_sectors,
        "domains": domain_summary,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "period": {
            "year": year,
            "month": month,
            "label": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "summary": summary,
        "nodes": nodes,
        "edges": edges,
    }
