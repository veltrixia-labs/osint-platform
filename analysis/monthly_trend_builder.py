"""
Monthly Trend Flow — extraction + flow aggregation.

Builds one month's flow/network snapshot from the Alert Stream:

  1. Pull every (non-suppressed) AlertLog in the calendar month. Alerts are
     already 24h-cluster-deduped at creation (jobs/alert_manager.py), so this is
     a straight time-window read.
  2. IMPORTANCE-primary selection: keep an alert when importance_score >= 50
     (the headline axis), or as a fallback when the stored anomaly intensity_pct is
     sufficiently high. No spike/baseline computation.
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

SCHEMA_VERSION = "monthly_trend_v3"  # v3: self-contained — embeds per-signal payloads (no live alert fetch)
# MTF selection axis = IMPORTANCE (mirrors Alert Stream anomaly->importance migration).
# PRIMARY: importance >= MTF_MIN_IMPORTANCE archives unconditionally. FALLBACK for
# importance-absent/low rows: stored anomaly intensity_pct >= the fallback floor.
# The former 1.5x-spike + 82 anomaly gates are removed (importance and anomaly are
# orthogonal, so those gates silently dropped every major story).
MTF_MIN_IMPORTANCE = 50.0
MIN_ARCHIVE_INTENSITY_FALLBACK_PCT = 60.0
# Month window spans ~30 days; the physics engine's window_hours only scales a few
# density proxies, so a 30-day window keeps the cluster-density math sane.
_MONTH_WINDOW_HOURS = 24.0 * 31
# Cap embedded sources per signal — keeps the frozen snapshot compact while still
# covering the detail pane's 3 primary + a few secondary sources.
_MAX_EVIDENCE_PER_SIGNAL = 6

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


def _signal_payload(alert, domain_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, SELF-CONTAINED snapshot of one spiked alert — everything the UI
    chart / list / detail pane need WITHOUT re-reading the (purgeable) alert_logs
    row. Field names mirror the GET /api/alerts/{id} contract so the frontend
    consumes these identically to live-fetched alerts."""
    ev = [e for e in (meta.get("evidence_list") or []) if isinstance(e, dict)][:_MAX_EVIDENCE_PER_SIGNAL]
    src = next((e.get("url") or e.get("link") for e in ev if (e.get("url") or e.get("link"))), None)
    return {
        "id": str(alert.id),
        "title": meta.get("display_title") or alert.target_label or "",
        "target_label": alert.target_label,
        "topic": alert.topic,
        "domain_id": domain_id,
        "triggered_at": alert.triggered_at.isoformat() if alert.triggered_at else None,
        "severity": alert.severity,
        "status": alert.status,
        "backbone_discovery_status": meta.get("backbone_discovery_status", "idle"),
        "intensity_pct": meta.get("intensity_pct"),
        "importance_score": meta.get("importance_score"),
        "importance_rationale": meta.get("importance_rationale"),
        "is_locked": False,
        "source_url": src,
        "evidence_list": ev,
    }


async def build_monthly_trend_snapshot(
    session: AsyncSession, year: int, month: int
) -> Dict[str, Any]:
    """Compute the flow snapshot dict for a calendar month (no DB writes)."""
    start, end, label = month_bounds(year, month)

    # Stream the month's alerts in 500-row partitions (server-side cursor) instead
    # of materializing the whole window as one list — keeps the result buffer flat.
    stmt = (
        select(AlertLog)
        .where(
            AlertLog.triggered_at >= start,
            AlertLog.triggered_at < end,
            AlertLog.suppressed.is_(False),
        )
        .order_by(AlertLog.triggered_at.asc())
        .execution_options(yield_per=500)
    )

    # Offline geocoder (text → lat/lon) is optional; fall back to row coords.
    geo = None
    try:
        from analysis.pro_geo_locator import GeoLocator
        geo = GeoLocator()
    except Exception as exc:  # FileNotFoundError when geo DB absent, etc.
        logger.info("monthly_trend: GeoLocator unavailable (%s); using row coordinates only.", exc)

    engine = SpatialPhysicsEngine(window_hours=_MONTH_WINDOW_HOURS)

    # Per-STRATEGIC-domain independent populations (the 6 canonical domains).
    spiked_ids_by_domain: Dict[str, List[str]] = defaultdict(list)  # ALL spikes, time-ordered
    events_by_domain: Dict[str, list] = defaultdict(list)      # mappable spikes → spatial events
    total_by_domain: Dict[str, int] = defaultdict(int)
    signals: List[Dict[str, Any]] = []                         # self-contained per-spike payloads
    # (strategic_domain, site_key) -> [alert_id]
    provenance: Dict[Tuple[str, str], List[str]] = defaultdict(list)

    total = 0
    result = await session.stream_scalars(stmt)
    async for alert in result:
        total += 1
        # Pass the headline so the sports/entertainment guardrail can intercept
        # items (e.g. World Cup) before macro keyword collisions misroute them.
        meta = alert.metadata_json if isinstance(alert.metadata_json, dict) else {}
        alert_text = f"{alert.target_label or ''} {meta.get('display_title', '')}"
        domain = infer_domain_from_topic(alert.topic or "", text=alert_text)
        total_by_domain[domain] += 1
        # IMPORTANCE-PRIMARY admission. importance >= MTF_MIN_IMPORTANCE archives
        # unconditionally; otherwise fall back to the stored anomaly intensity_pct.
        imp = meta.get("importance_score")
        pct = meta.get("intensity_pct")
        imp_ok = isinstance(imp, (int, float)) and float(imp) >= MTF_MIN_IMPORTANCE
        pct_ok = isinstance(pct, (int, float)) and float(pct) >= MIN_ARCHIVE_INTENSITY_FALLBACK_PCT
        if not (imp_ok or pct_ok):
            continue

        spiked_ids_by_domain[domain].append(str(alert.id))
        signals.append(_signal_payload(alert, domain, meta))

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
        "top_sectors": top_sectors,
        "domains": domain_summary,
        "signals": signals,  # self-contained: UI renders chart/list/detail from these
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
