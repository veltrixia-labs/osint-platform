"""
Pro Structural Context Engine.

Aggregates macroeconomic structural data and market price data for a specific domain
to provide analytical context for Pro Structural Briefs.
"""

import re
import uuid
import logging
from typing import Optional, List, Dict, Any, Set, Tuple
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ExternalDataSeries,
    ExternalObservation,
    ExternalTradeFlow,
    ExternalIndustryStat,
    MarketDataInstrument,
    MarketDataPrice,
    AlertLog,
    Item,
    SystemicFragilityLog,
    SpatialNode,
    SpatialEdge,
)
from analysis.spatial_composite_risk import topic_to_spatial_domain
from analysis.pro_domain_config import (
    PRO_DOMAIN_CONFIG,
    get_pro_domain_config,
    infer_domain_from_topic,
)
from analysis.pro_global_series import (
    get_core_global_series_ids,
    merge_relevance_maps,
)
from analysis.pro_structural_compiler import (
    MIN_ALERT_CORRELATION,
    MIN_NEWS_CORRELATION,
    PRO_REPORT_CLUSTER_WINDOW_HOURS,
    PRO_REPORT_REIGNITE_FACTOR,
    _tokenize,
    build_cascading_impacts,
    build_quantitative_evidence_matrix,
    build_sector_vocabulary,
    build_tail_risk_scenarios,
    enforce_institutional_tone,
    filter_correlated_news_items,
    filter_correlated_timeline_events,
    structural_correlation_score,
)
from analysis.pro_systemic_physics import SystemicFragilityEngine
from analysis.pro_geo_locator import GeoLocator
from reports.text_encoding import sanitize_unicode_text, sanitize_unicode_tree

logger = logging.getLogger(__name__)

# Live alert clustering window — pinned to the institutional-grade Pro
# threshold. Re-exported as a module-level constant so other modules don't
# silently override it.
ALERT_CLUSTER_WINDOW_HOURS: int = PRO_REPORT_CLUSTER_WINDOW_HOURS
ALERT_REIGNITE_INTENSITY_FACTOR: float = PRO_REPORT_REIGNITE_FACTOR

# Domain → primary macro series for the macro_transmission engine. Picked as
# the canonical leading indicator per sector (see pro_domain_config relevance maps).
_DOMAIN_PRIMARY_MACRO: Dict[str, str] = {
    "energy_resource_risk":            "DCOILWTICO",
    "global_market_intelligence":      "DGS10",
    "ai_semiconductor_intelligence":   "PCU334413334413",
    "supply_chain_intelligence":       "WPU101",
    "defense_technology":              "FDEFX",
    "crypto_geopolitics":              "DTWEXBGS",
}

# Domain → canonical UPPER topic used by AlertLog.topic.
_DOMAIN_TO_UPPER_TOPIC: Dict[str, str] = {
    "energy_resource_risk":            "ENERGY",
    "global_market_intelligence":      "MARKET",
    "ai_semiconductor_intelligence":   "AI_TECH",
    "supply_chain_intelligence":       "SUPPLY_CHAIN",
    "defense_technology":              "DEFENSE",
    "crypto_geopolitics":              "CRYPTO",
}


async def _compute_quantitative_evidence(
    db: AsyncSession,
    domain_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Run the MacroTransmissionEngine for the domain's primary macro/topic pair.

    Returns the engine's payload (lag_days, correlation, beta, series) augmented
    with sample_size / include_inverse, or None if no mapping exists. Failures
    are swallowed (with a warning) so a single engine miss can never block a
    report from being produced.
    """
    macro_series = _DOMAIN_PRIMARY_MACRO.get(domain_id)
    upper_topic = _DOMAIN_TO_UPPER_TOPIC.get(domain_id)
    if not macro_series or not upper_topic:
        return None
    try:
        # Local import to avoid pulling pandas/numpy when this module is loaded
        # by lightweight code paths (e.g. dashboard polling).
        from analysis.macro_transmission import MacroTransmissionEngine

        engine = MacroTransmissionEngine(db)
        result = await engine.compute_transmission_metrics(
            macro_series_id=macro_series,
            target_topic=upper_topic,
            days_lookback=90,
            roc_window=7,
            include_inverse=False,
        )
        if not isinstance(result, dict):
            return None
        result = dict(result)
        result["sample_size"] = len(result.get("series") or [])
        result["include_inverse"] = False
        # Strip the bulky raw series before storing in payload — the matrix
        # builder only needs the scalar metrics.
        result.pop("series", None)
        return result
    except Exception as exc:
        logger.warning(
            "Macro transmission engine skipped for %s/%s: %s",
            domain_id, macro_series, exc,
        )
        return None


# ─── Spatial Contagion (offline GeoLocator) ────────────────────────────

# Curated geo keyword list — **ordered by geopolitical specificity** so the
# first match becomes the spatial epicenter when a context mentions multiple
# entities (e.g. "Strait of Hormuz" beats "Iran" as the focal point of an
# OSINT contagion).
#
# Tier 1: chokepoints / straits / maritime corridors (most specific)
# Tier 2: major capital cities (single-point references)
# Tier 3: countries / broad regional names (last-resort)
_GEO_KEYWORDS: tuple = (
    # Tier 1 — chokepoints (most geopolitically focused)
    "Strait of Hormuz", "Hormuz",
    "Taiwan Strait", "Strait of Malacca",
    "Suez Canal", "Panama Canal",
    "Bab-el-Mandeb", "Bosphorus",
    "Gulf of Oman", "Persian Gulf", "South China Sea", "Red Sea",
    # Tier 2 — capital + financial-hub cities
    "Beijing", "Moscow", "Tokyo", "Tehran", "Riyadh", "Tel Aviv",
    "London", "Paris", "Berlin", "Washington", "New York", "Singapore",
    # Tier 3 — countries / broad regions
    "United States", "China", "Russia", "Japan", "South Korea", "Taiwan",
    "Iran", "Saudi Arabia", "UAE", "Iraq", "Israel", "Turkey",
    "Ukraine", "Germany", "France", "United Kingdom",
    "India", "Brazil", "Mexico", "Canada", "Australia", "Indonesia",
    "North Korea", "Pakistan", "Nigeria", "Venezuela", "Norway",
)

# Don't let a single brief explode into hundreds of geocoded points.
_SPATIAL_MAX_NODES = 10
_SPATIAL_MAX_CANDIDATES = 24    # candidates fed into the geocoder; deduped to MAX_NODES

# 2-hop expansion: when a 1st-hop "affected" node lives in country XX, we
# pick this country's flagship city as the order-3 ripple. The map is small
# and curated — we don't want random geocoder noise muddying the visual.
# Falls back silently when the country isn't here.
_ISO_TO_MAJOR_CITY: Dict[str, str] = {
    "US": "New York",       "CN": "Shanghai",       "JP": "Tokyo",
    "KR": "Seoul",          "DE": "Berlin",         "FR": "Paris",
    "GB": "London",         "IT": "Rome",           "RU": "Moscow",
    "IR": "Tehran",         "SA": "Riyadh",         "AE": "Dubai",
    "IL": "Tel Aviv",       "TR": "Istanbul",       "EG": "Cairo",
    "PA": "Panama City",    "BR": "Sao Paulo",      "MX": "Mexico City",
    "IN": "Mumbai",         "CA": "Toronto",        "AU": "Sydney",
    "SG": "Singapore",      "MY": "Kuala Lumpur",   "ID": "Jakarta",
    "TH": "Bangkok",        "VN": "Ho Chi Minh City","TW": "Taipei",
    "PH": "Manila",         "NG": "Lagos",          "ZA": "Johannesburg",
    "UA": "Kyiv",           "PL": "Warsaw",         "NL": "Amsterdam",
    "BE": "Brussels",       "ES": "Madrid",         "PT": "Lisbon",
    "NO": "Oslo",           "SE": "Stockholm",      "FI": "Helsinki",
    "DK": "Copenhagen",     "GR": "Athens",
}

# Slot allocation per order so a deeply-cascaded scenario doesn't crowd out
# the primary signal. Conservative defaults; the engine will only fill what
# the geocoder can actually resolve (no placeholders).
_SPATIAL_BUDGET_ORDER1 = 1        # exactly one epicenter
_SPATIAL_BUDGET_ORDER2 = 6        # up to 6 direct-impact affected nodes
_SPATIAL_BUDGET_ORDER3 = 3        # up to 3 2-hop downstream nodes


def _get_field(item: Any, key: str, default: Any = None) -> Any:
    """Safe attr-or-key accessor — context lists mix ORM rows and dicts."""
    if item is None:
        return default
    if hasattr(item, key):
        return getattr(item, key, default)
    if isinstance(item, dict):
        return item.get(key, default)
    return default


def _harvest_entity_candidates(context: Dict[str, Any]) -> List[str]:
    """
    Pull plausible location strings out of a Pro context. Returns a
    PRIORITY-ORDERED, deduplicated list — the first resolved candidate
    becomes the epicenter, so ordering matters.

    Strategy: two passes.

      Pass 1 — **Canonical geo keywords** found in any text source. These
                are the cleanest matches for the offline geocoder (single
                place name, no noise words), so they get the top slots.
                The order inside the keyword list itself is preserved so a
                signal mentioning "Strait of Hormuz" beats one only
                mentioning "Iran".
      Pass 2 — Raw `target_label` / `location_label` strings as a fallback.
                These can be noisy (e.g. "Strait of Hormuz pipeline rupture")
                so FTS5 may reject them — but on the rare row where the
                full string IS the canonical entry, this pass still wins.
    """
    out: List[str] = []
    seen: Set[str] = set()

    def _push(text: Any) -> None:
        if not isinstance(text, str):
            return
        s = text.strip()
        if not s:
            return
        key = s.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(s)

    sig = context.get("signal") or {}

    # ── Collect every text source we might mine geo keywords from. ────────
    text_sources: List[str] = []
    for k in ("target_label", "title"):
        v = sig.get(k)
        if isinstance(v, str):
            text_sources.append(v)
    for ev in context.get("related_events") or []:
        v = _get_field(ev, "target_label")
        if isinstance(v, str):
            text_sources.append(v)
    for ev in context.get("event_timeline") or []:
        for k in ("location_label", "title"):
            v = _get_field(ev, k)
            if isinstance(v, str):
                text_sources.append(v)
    for n in (sig.get("related_news") or [])[:8]:
        for k in ("title", "headline", "text"):
            v = _get_field(n, k)
            if isinstance(v, str):
                text_sources.append(v)
                break

    combined_lower = " | ".join(text_sources).lower()

    # Pass 1: canonical geo keywords (high-quality, single-name matches)
    for kw in _GEO_KEYWORDS:
        if kw.lower() in combined_lower:
            _push(kw)

    # Pass 2: raw priority strings (last-resort fallback)
    _push(sig.get("target_label"))
    for ev in context.get("related_events") or []:
        _push(_get_field(ev, "target_label"))
    for ev in context.get("event_timeline") or []:
        _push(_get_field(ev, "location_label"))

    return out[:_SPATIAL_MAX_CANDIDATES]


def _scale_viscosity_to_impact(viscosity: Optional[float]) -> float:
    """
    Map kinematic viscosity → [0, 100] impact score.

    SystemicFragilityEngine.VISCOSITY_CRITICAL = 0.10. We center the scale
    so that critical viscosity (the conjunction trigger) lands at 50, and
    2× critical fully saturates at 100. Below zero or non-finite inputs
    collapse to 0 — never NaN in the payload.
    """
    if viscosity is None:
        return 0.0
    try:
        v = float(viscosity)
    except (TypeError, ValueError):
        return 0.0
    if not (v == v) or v <= 0:  # NaN-safe
        return 0.0
    # 0.10 → 50, 0.20 → 100, > 0.20 clipped to 100
    return round(min(100.0, v * 500.0), 2)


def _scale_entropy_to_intensity(entropy: Optional[float]) -> float:
    """Edge intensity = normalised entropy, clipped to [0, 1]."""
    if entropy is None:
        return 0.0
    try:
        e = float(entropy)
    except (TypeError, ValueError):
        return 0.0
    if not (e == e):
        return 0.0
    return round(min(1.0, max(0.0, e)), 4)


async def _fetch_live_spatial_graph(
    db: AsyncSession,
    *,
    topic_code: str,
) -> Optional[Dict[str, Any]]:
    """
    Pull the spatial contagion graph from the spatial tables for the domain
    ``topic_code`` resolves to (see ``topic_to_spatial_domain``).

    Returns the `spatial_contagion` shape the frontend Pro Brief understands
    when the resolved domain has a loaded cascade, or ``None`` when it has no
    nodes — so the brief renders NO spatial section rather than a 'global'
    relic aggregate or an "Awaiting Spatial Data" placeholder that would assert
    data is pending when no cascade exists for this topic.
    """
    short_id = topic_to_spatial_domain(topic_code)

    async def _load(domain_id: str) -> Tuple[List[SpatialNode], List[SpatialEdge]]:
        nodes = (
            await db.execute(
                select(SpatialNode).where(SpatialNode.domain_id == domain_id)
            )
        ).scalars().all()
        edges = (
            await db.execute(
                select(SpatialEdge).where(SpatialEdge.domain_id == domain_id)
            )
        ).scalars().all()
        return list(nodes), list(edges)

    nodes, edges = await _load(short_id)
    used_domain = short_id
    if not nodes:
        # A topic with no real cascade renders NO spatial section. We return None
        # (the caller/payload/frontend all treat that as clean absence). We do NOT
        # fall back to a relic 'global' aggregate, and we do NOT emit an empty
        # graph: an "Awaiting Spatial Data" placeholder would assert that data is
        # coming when none exists for this topic.
        return None

    # None survives as None: an UNMEASURED magnitude is not zero. `float(None)` would
    # raise, and coercing it to 0.0 would assert "no impact" about something we never
    # measured. The renderer's exposed_unquantified path already handles a null.
    def _nf(v: Optional[float]) -> Optional[float]:
        return None if v is None else float(v)

    serialised_nodes: List[Dict[str, Any]] = [
        {
            # Vault canonical id when present (the edge join key); otherwise the row
            # UUID — byte-identical to the previous behaviour while node_id is NULL.
            "id": n.node_id or str(n.id),
            "name": n.name,
            "lat": float(n.lat),
            "lon": float(n.lon),
            "impact_score": _nf(n.impact_score),
            "entropy_index": float(n.entropy_index),
            "type": n.node_type or ("epicenter" if n.is_epicenter else "affected"),
            "country": n.country,
            "order": n.order_level,
            "confidence": n.confidence,
            "why": n.why,
            "has_unquantified_direct_edge": bool(n.has_unquantified_direct_edge),
        } for n in nodes
    ]
    serialised_edges: List[Dict[str, Any]] = [
        {
            "source_lat": float(e.source_lat),
            "source_lon": float(e.source_lon),
            "target_lat": float(e.target_lat),
            "target_lon": float(e.target_lon),
            "intensity": _nf(e.edge_intensity),
            "edge_intensity": _nf(e.edge_intensity),
            "unquantified": bool(e.unquantified),
            "source_id": e.source_node_id,
            "target_id": e.target_node_id,
            "viscosity_coefficient": float(e.viscosity_coefficient),
            "order_level": int(e.order_level),
            "target_order": int(e.order_level),
        } for e in edges
    ]

    # Aggregates EXCLUDE unmeasured magnitudes — and the DIVISOR counts only the
    # edges actually summed, so an unmeasured edge cannot dilute the mean.
    measured_scores = [float(n.impact_score) for n in nodes if n.impact_score is not None]
    measured_intensities = [
        float(e.edge_intensity) for e in edges if e.edge_intensity is not None
    ]

    if measured_scores:
        epicenter_impact = max(measured_scores)
    elif nodes:
        # Nodes exist but nothing is measured. The renderer divides by this value,
        # so a 0 would be a divide-by-zero -> 1.0 sentinel.
        epicenter_impact = 1.0
    else:
        epicenter_impact = 0.0  # no nodes at all — unchanged from today
    mean_intensity = (
        sum(measured_intensities) / len(measured_intensities)
        if measured_intensities else 0.0
    )
    order_counts = {1: 0, 2: 0, 3: 0}
    for e in edges:
        if e.order_level in order_counts:
            order_counts[e.order_level] += 1

    return {
        "domain_id": used_domain,
        "topic_code": topic_code,
        "nodes": serialised_nodes,
        "edges": serialised_edges,
        "epicenter_impact_score": epicenter_impact,
        "edge_intensity": mean_intensity,
        "node_count": len(serialised_nodes),
        "edge_count": len(serialised_edges),
        "order_counts": {
            "order_1": order_counts[1],
            "order_2": order_counts[2],
            "order_3": order_counts[3],
        },
        "schema_version": "spatial_engine_v1",
    }


def _compute_spatial_contagion(
    context: Dict[str, Any],
    systemic_fragility: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the `spatial_contagion` object from a Pro context.

    Strategy (Phase 2 — N-th Order Impact Graph):
      1. Harvest entity candidates (signal target_label, related_events,
         timeline labels, scanned geo keywords).
      2. Resolve each via the offline ``GeoLocator``; dedupe by rounded
         (lat, lon).
      3. **Order 1**: the first resolved entity → epicenter (impact_score
         derived from kinematic viscosity).
      4. **Order 2**: remaining direct candidates → affected nodes
         (impact_score decays 10% per rank, floored 30% of epicenter).
      5. **Order 3** (NEW): for each order-2 node, look up its country's
         flagship city via ``_ISO_TO_MAJOR_CITY`` and geocode it. These
         2-hop downstream ripples are added only if the geocoder resolves
         AND the city isn't already in the graph (no duplicate coords).
      6. Edges: one per affected/downstream node, source = epicenter,
         intensity scaled by network entropy. Edge.target_order mirrors
         the target node's order so the frontend can per-tier style arcs.

    Returns ``{"nodes": [], "edges": []}`` (with a `warning` field) when no
    entity can be resolved or the geo DB is missing. Never raises.
    """
    sf = systemic_fragility or {}
    viscosity = sf.get("viscosity_coefficient")
    entropy = sf.get("entropy_index")
    epi_score = _scale_viscosity_to_impact(viscosity)
    edge_intensity = _scale_entropy_to_intensity(entropy)

    payload: Dict[str, Any] = {
        "nodes": [],
        "edges": [],
        "epicenter_impact_score": epi_score,
        "edge_intensity": edge_intensity,
        "viscosity_coefficient": float(viscosity) if isinstance(viscosity, (int, float)) else None,
        "entropy_index": float(entropy) if isinstance(entropy, (int, float)) else None,
        # Bumped to v2 — adds node.order and edge.target_order
        "schema_version": "spatial_contagion_v2",
    }

    candidates = _harvest_entity_candidates(context)
    if not candidates:
        payload["warning"] = "no_entity_candidates"
        return payload

    try:
        geo = GeoLocator()
    except FileNotFoundError as exc:
        logger.warning("Spatial contagion: geo DB missing (%s) — emitting empty payload.", exc)
        payload["warning"] = "geo_db_unavailable"
        return payload

    resolved: List[Dict[str, Any]] = []
    coord_keys: Set[Tuple[float, float]] = set()

    def _resolve(raw: str) -> Optional[Dict[str, Any]]:
        """Geocode + dedupe-by-coordinate helper used for both 1-hop and 2-hop passes."""
        hit = geo.get_coordinates(raw)
        if not hit:
            return None
        key = (round(float(hit["lat"]), 3), round(float(hit["lon"]), 3))
        if key in coord_keys:
            return None
        coord_keys.add(key)
        return {
            "raw_input": raw,
            "name": hit.get("name"),
            "lat": float(hit["lat"]),
            "lon": float(hit["lon"]),
            "country": hit.get("country"),
            "confidence": hit.get("confidence"),
            "geonameid": hit.get("geonameid"),
        }

    try:
        # ── 1st pass: direct entity resolution (epicenter + order-2 affected) ──
        order2_budget = _SPATIAL_BUDGET_ORDER1 + _SPATIAL_BUDGET_ORDER2
        for raw in candidates:
            if len(resolved) >= order2_budget:
                break
            row = _resolve(raw)
            if row is not None:
                resolved.append(row)

        # ── 2nd pass: 2-hop expansion via country's flagship city. ──
        # We only run this when at least one order-2 affected node exists;
        # without one, "deeper" downstream has no anchor.
        order3_rows: List[Dict[str, Any]] = []
        affected_resolved = resolved[1:]  # skip the epicenter
        if affected_resolved:
            for affected in affected_resolved:
                if len(order3_rows) >= _SPATIAL_BUDGET_ORDER3:
                    break
                iso = (affected.get("country") or "").upper().strip()
                if not iso:
                    continue
                city = _ISO_TO_MAJOR_CITY.get(iso)
                if not city:
                    continue
                # Skip when the country's flagship city IS the affected node
                # itself (e.g. epicenter "Tokyo" + affected_1 "JP" would otherwise
                # try to resolve "Tokyo" → already in coord_keys → skipped, but
                # an explicit short-circuit keeps the log noise down).
                aff_name = (affected.get("name") or "").casefold().strip()
                if aff_name == city.casefold().strip():
                    continue
                row = _resolve(city)
                if row is not None:
                    order3_rows.append(row)
    finally:
        geo.close()

    if not resolved:
        payload["warning"] = "no_resolved_locations"
        return payload

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # ── Order 1: Epicenter ─────────────────────────────────────────────
    epi = resolved[0]
    epi_id = "epicenter"
    nodes.append({
        "id": epi_id,
        "name": epi["name"],
        "raw_input": epi["raw_input"],
        "lat": epi["lat"],
        "lon": epi["lon"],
        "country": epi["country"],
        "impact_score": epi_score,
        "type": "epicenter",
        "order": 1,
        "confidence": epi["confidence"],
        "geonameid": epi["geonameid"],
    })

    # ── Order 2: Direct affected nodes ─────────────────────────────────
    for idx, n in enumerate(affected_resolved, start=1):
        node_id = f"affected_{idx}"
        decay = max(0.30, 1.0 - 0.10 * idx)
        affected_score = round(epi_score * decay, 2)
        nodes.append({
            "id": node_id,
            "name": n["name"],
            "raw_input": n["raw_input"],
            "lat": n["lat"],
            "lon": n["lon"],
            "country": n["country"],
            "impact_score": affected_score,
            "type": "affected",
            "order": 2,
            "confidence": n["confidence"],
            "geonameid": n["geonameid"],
        })
        edges.append({
            "source_id": epi_id,
            "target_id": node_id,
            "intensity": edge_intensity,
            "target_order": 2,
        })

    # ── Order 3: 2-hop downstream (country flagship cities) ────────────
    # Edges fan out from the epicenter (not from order-2) so the visual
    # remains a star-graph; the order signal alone communicates the depth.
    base_affected_count = len(affected_resolved)
    for offset, n in enumerate(order3_rows):
        node_idx = base_affected_count + offset + 1
        node_id = f"downstream_{offset + 1}"
        # Deeper ripples — start at 35% of epicenter and drop slowly.
        downstream_score = round(epi_score * max(0.20, 0.35 - 0.05 * offset), 2)
        nodes.append({
            "id": node_id,
            "name": n["name"],
            "raw_input": n["raw_input"],
            "lat": n["lat"],
            "lon": n["lon"],
            "country": n["country"],
            "impact_score": downstream_score,
            "type": "affected",
            "order": 3,
            "confidence": n["confidence"],
            "geonameid": n["geonameid"],
        })
        # Edge intensity slightly attenuated for deeper nodes — multiply by
        # 0.6 so the per-order styling story is reinforced in the data too.
        edges.append({
            "source_id": epi_id,
            "target_id": node_id,
            "intensity": round(edge_intensity * 0.6, 4),
            "target_order": 3,
        })
        # Suppress unused var lint when budget tier sizes change later.
        _ = node_idx

    payload["nodes"] = nodes
    payload["edges"] = edges
    payload["node_count"] = len(nodes)
    payload["edge_count"] = len(edges)
    payload["order_counts"] = {
        "order_1": sum(1 for n in nodes if n.get("order") == 1),
        "order_2": sum(1 for n in nodes if n.get("order") == 2),
        "order_3": sum(1 for n in nodes if n.get("order") == 3),
    }
    payload["candidates_inspected"] = len(candidates)
    return payload


async def _persist_systemic_fragility(
    db: AsyncSession,
    domain_id: str,
    payload: Optional[Dict[str, Any]],
) -> None:
    """
    Append one row to ``systemic_fragility_log`` capturing the engine output
    for this domain at this pipeline cycle.

    The persistence is "best effort" — a single insert failure must never
    block report generation, so we catch broadly and log.  We also skip
    rows where the engine self-reported INSUFFICIENT DATA: those are not
    interesting trajectory points and would only pollute the time series.
    """
    if not payload or not domain_id:
        return
    if payload.get("label") == "INSUFFICIENT DATA":
        return
    try:
        row = SystemicFragilityLog(
            domain_id=domain_id,
            entropy_index=float(payload.get("entropy_index") or 0.0),
            viscosity_coefficient=float(payload.get("viscosity_coefficient") or 0.0),
            label=str(payload.get("label") or "UNKNOWN")[:64],
            phase_transition_warning=bool(payload.get("phase_transition_warning")),
            sample_size=int(payload.get("sample_size") or 0) if payload.get("sample_size") is not None else None,
            raw_payload=payload,
        )
        db.add(row)
        await db.commit()
    except Exception as exc:
        # Roll back the failed insert so the outer session stays usable.
        try:
            await db.rollback()
        except Exception:
            pass
        logger.warning(
            "Persisting systemic_fragility row failed for %s: %s",
            domain_id, exc, exc_info=True,
        )


def _compute_systemic_fragility(
    *,
    market_ctx: Optional[Dict[str, Any]] = None,
    structural_ctx: Optional[Dict[str, Any]] = None,
    related_events: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Build the volatility series + flow proxy for `SystemicFragilityEngine` and
    return its full analyse() payload.

    Volatility series  = concatenated percent moves from the latest market
                         instruments AND macro observations. Combining both
                         gives the engine a wide cross-asset view of disorder.
    Volume flow        = count of related alerts in the cluster window
                         (institutional "demand" proxy). When alert flow is
                         absorbing the variance, viscosity stays low.

    Failures never propagate — we return a STABLE / INSUFFICIENT-DATA payload
    rather than letting one bad metric block report generation.
    """
    try:
        volatility_series: List[float] = []
        for price in (market_ctx or {}).get("latest_prices") or []:
            pct = price.get("percent_change")
            if isinstance(pct, (int, float)) and pct == pct:  # NaN-safe
                volatility_series.append(float(pct))
        for obs in (structural_ctx or {}).get("macro_observations") or []:
            chg = obs.get("change_pct")
            if isinstance(chg, (int, float)) and chg == chg:
                volatility_series.append(float(chg))

        # Volume flow = institutional alert throughput across the cluster
        # window. We deliberately use the count (not intensity sum) so a
        # single very-high-intensity alert doesn't dominate.
        volume_flow = float(len(related_events or []))

        engine = SystemicFragilityEngine()
        payload = engine.analyse(volatility_series, volume_flow=volume_flow)
        payload["engine"] = "SystemicFragilityEngine"
        payload["schema_version"] = "systemic_fragility_v1"
        return payload
    except Exception as exc:
        logger.warning("Systemic fragility engine skipped: %s", exc, exc_info=True)
        return {
            "entropy_index": 0.0,
            "viscosity_coefficient": 0.0,
            "entropy_critical": False,
            "viscosity_critical": False,
            "phase_transition_warning": False,
            "label": "INSUFFICIENT DATA",
            "rationale": f"Systemic fragility engine error: {exc!s}",
            "engine": "SystemicFragilityEngine",
            "schema_version": "systemic_fragility_v1",
        }


async def resolve_latest_domain_alert(
    db: AsyncSession,
    domain_id: str,
    *,
    window_hours: int = ALERT_CLUSTER_WINDOW_HOURS,
) -> Optional[AlertLog]:
    """
    Pick the highest-scoring alert in the live clustering window for a Pro domain.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    stmt = (
        select(AlertLog)
        .where(
            AlertLog.triggered_at >= since,
            AlertLog.suppressed == False,  # noqa: E712
        )
        .order_by(desc(AlertLog.triggered_at), desc(AlertLog.intelligence_score))
        .limit(120)
    )
    rows = (await db.execute(stmt)).scalars().all()
    best: Optional[AlertLog] = None
    best_score = -1.0
    for row in rows:
        if infer_domain_from_topic(row.topic or "") != domain_id:
            continue
        score = float(row.intelligence_score or 0.0)
        if best is None or score > best_score:
            best = row
            best_score = score
    return best


def _build_predictive_forecast(
    domain_id: str,
    domain_display: str,
    macro_obs: List[dict],
    market_ctx: dict,
    *,
    alert_depleted: bool,
) -> Dict[str, Any]:
    """
    Rule-based macro risk outlook when the 24h alert cluster is empty.
    Keeps the intelligence stream alive without LLM dependency.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    risk_vectors: List[str] = []
    for obs in (macro_obs or [])[:8]:
        chg = obs.get("change_pct")
        label = obs.get("display_name") or obs.get("series_id") or "Macro series"
        if chg is None:
            continue
        if chg > 0.75:
            risk_vectors.append(f"{label}: upward structural pressure ({chg:+.2f}% lookback)")
        elif chg < -0.75:
            risk_vectors.append(f"{label}: downward structural pressure ({chg:+.2f}% lookback)")
        else:
            risk_vectors.append(f"{label}: range-bound ({chg:+.2f}% lookback)")

    prices = market_ctx.get("latest_prices") or []
    for price in prices[:4]:
        pct = price.get("percent_change")
        sym = price.get("symbol") or "Instrument"
        if pct is None:
            continue
        risk_vectors.append(f"{sym}: session move {pct:+.2f}% (market confirmation layer)")

    mode = "macro_predictive" if alert_depleted else "alert_anchored"
    if alert_depleted and not risk_vectors:
        risk_vectors.append(
            f"No live alerts in the last {ALERT_CLUSTER_WINDOW_HOURS}h; "
            "quantitative feeds are the sole active signal layer."
        )

    headline = (
        f"Predictive structural outlook for {domain_display}: "
        + (risk_vectors[0] if risk_vectors else "monitoring macro and market feeds in real time.")
    )
    return {
        "mode": mode,
        "generated_at": generated_at,
        "headline": headline,
        "risk_vectors": risk_vectors,
        "confidence": "moderate" if len(risk_vectors) >= 2 else "low",
        "alert_cluster_depleted": alert_depleted,
    }


async def build_pro_structural_context(
    db: AsyncSession,
    alert_log: Optional[AlertLog] = None,
    domain_id: Optional[str] = None,
    topic: Optional[str] = None,
    lookback_days: int = 30,
    *,
    force_rebuild: bool = True,
    analysis_generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Builds a rich context dictionary for a Pro Structural Brief.
    """
    # 1. Resolve Domain ID
    resolved_domain_id = domain_id
    if not resolved_domain_id and alert_log:
        resolved_domain_id = infer_domain_from_topic(alert_log.topic)
    if not resolved_domain_id and topic:
        resolved_domain_id = infer_domain_from_topic(topic)
    if not resolved_domain_id:
        resolved_domain_id = "global_market_intelligence"
    
    config = get_pro_domain_config(resolved_domain_id)
    if not config:
        config = get_pro_domain_config("global_market_intelligence")
        resolved_domain_id = "global_market_intelligence"

    data_notes = []
    analysis_ts = analysis_generated_at or datetime.now(timezone.utc)

    # 2. Signal / Alert Context — bind to 24h domain cluster when no explicit alert
    if not alert_log and resolved_domain_id:
        alert_log = await resolve_latest_domain_alert(db, resolved_domain_id)
        if alert_log:
            data_notes.append(
                f"Anchored to latest {ALERT_CLUSTER_WINDOW_HOURS}h domain alert cluster."
            )
        else:
            data_notes.append(
                f"No alerts in the last {ALERT_CLUSTER_WINDOW_HOURS}h for this domain; "
                "using macro predictive forecasting layer."
            )

    signal_ctx = None
    related_news = []
    if alert_log:
        meta = alert_log.metadata_json or {}
        # Pro-owned related-news (sourced from the alert's evidence_list). The
        # former dependency on the deprecated free_alert payload was removed.
        related_news = _related_news_from_evidence(meta)

        signal_ctx = {
            "alert_id": str(alert_log.id),
            "title": sanitize_unicode_text(alert_log.target_label or ""),
            "topic": alert_log.topic,
            "severity": alert_log.severity,
            "trigger_type": alert_log.trigger_type,
            "target_label": sanitize_unicode_text(alert_log.target_label or ""),
            "intensity": alert_log.intensity,
            "intelligence_score": alert_log.intelligence_score,
            "fidelity_score": alert_log.fidelity_score,
            "location_lat": alert_log.location_lat,
            "location_lng": alert_log.location_lng,
            "triggered_at": alert_log.triggered_at.isoformat() if alert_log.triggered_at else None,
            "source_url": _first_evidence_url(meta),
            "related_news": related_news[:5]  # Limit to top 5
        }

    merged_relevance = merge_relevance_maps(config.get("relevance_map", {}))
    sector_vocabulary = build_sector_vocabulary(config, merged_relevance)
    trigger_tokens: Set[str] = set()
    if signal_ctx and signal_ctx.get("title"):
        trigger_tokens = _tokenize(signal_ctx["title"])

    related_news = filter_correlated_news_items(
        related_news,
        sector_vocabulary,
        trigger_tokens=trigger_tokens,
    )
    if signal_ctx:
        signal_ctx["related_news"] = related_news[:5]

    related_events = await _fetch_related_alert_events(
        db,
        alert_log,
        resolved_domain_id,
        data_notes,
        limit=8,
        window_hours=ALERT_CLUSTER_WINDOW_HOURS,
        vocabulary=sector_vocabulary,
        trigger_tokens=trigger_tokens,
    )

    # 3. Event timeline: correlated domain alerts + news only
    event_timeline = _build_event_timeline(
        related_news,
        signal_ctx,
        related_events=related_events,
        vocabulary=sector_vocabulary,
        trigger_tokens=trigger_tokens,
    )

    # 4. Structural Context Data
    structural_ctx = {
        "macro_observations": await _get_macro_observations(
            db, config, lookback_days, data_notes, resolved_domain_id
        ),
        "trade_flows": await _get_trade_flows(db, config, data_notes),
        "industry_stats": await _get_industry_stats(db, config, data_notes)
    }

    # 5. Market Confirmation Data
    market_ctx = await _get_market_confirmation(db, config, lookback_days, data_notes)

    # 6. Complement Watch Indicators
    watch_indicators = await _complement_watch_indicators(db, config.get("watch_indicators", []), data_notes)

    alert_depleted = alert_log is None and not related_events
    predictive_forecast = _build_predictive_forecast(
        resolved_domain_id,
        config.get("display_name", resolved_domain_id),
        structural_ctx.get("macro_observations") or structural_ctx.get("macro_display_cards") or [],
        market_ctx,
        alert_depleted=alert_depleted,
    )

    # 6.5 Quantitative evidence: cross-correlation + beta from MacroTransmissionEngine.
    quantitative_evidence = await _compute_quantitative_evidence(db, resolved_domain_id)

    # 6.55 Systemic Fragility: Shannon entropy + kinematic viscosity over the
    # cross-asset volatility distribution. Drives the phase-transition warning.
    systemic_fragility = _compute_systemic_fragility(
        market_ctx=market_ctx,
        structural_ctx=structural_ctx,
        related_events=related_events,
    )
    # Append a trajectory point to systemic_fragility_log so the dashboard
    # can plot the 2D phase-space history. Failures are swallowed (the
    # helper rolls back its own session usage) — never block the brief.
    await _persist_systemic_fragility(db, resolved_domain_id, systemic_fragility)

    # 6.575 Spatial Contagion — Phase 7.4 unification.
    # Single source of truth: the live Spatial Engine tables. The inline
    # _compute_spatial_contagion() path is no longer invoked for new briefs;
    # we fetch the graph the 5-minute worker has already persisted.
    spatial_contagion_payload = await _fetch_live_spatial_graph(
        db, topic_code=resolved_domain_id,
    )

    # 6.6 Structured analytical sections grounded in quantitative data.
    cascading_impacts = build_cascading_impacts(
        config,
        macro_observations=structural_ctx.get("macro_observations") or [],
    )
    tail_risk_scenarios = build_tail_risk_scenarios(
        config,
        macro_observations=structural_ctx.get("macro_observations") or [],
        quantitative_evidence=quantitative_evidence,
    )
    quantitative_evidence_matrix = build_quantitative_evidence_matrix(
        macro_observations=structural_ctx.get("macro_observations") or [],
        market_prices=market_ctx.get("latest_prices") or [],
        quantitative_evidence=quantitative_evidence,
        related_events=related_events,
    )

    # 7. Build Final Context
    context = {
        "domain": {
            "domain_id": config["domain_id"],
            "display_name": config["display_name"],
            "primary_user_question": config["primary_user_question"],
            "primary_asset_classes": config["primary_asset_classes"],
            "decision_relevant_questions": config["decision_relevant_questions"]
        },
        "signal": signal_ctx,
        "related_events": related_events,
        "event_timeline": event_timeline,
        "structural_context": structural_ctx,
        "market_confirmation": market_ctx,
        "watch_indicators": watch_indicators,
        "transmission_channels": config.get("transmission_channels", []),
        "exposure_targets": config.get("exposure_targets", []),
        "balanced_interpretations": config.get("balanced_interpretations", {}),
        "data_freshness": _calculate_freshness(structural_ctx, market_ctx),
        "data_notes": data_notes,
        # New analytical config fields (passed through for payload builder)
        "signal_classification_template": config.get("signal_classification_template", {}),
        "relevance_map": merged_relevance,
        "market_group_map": config.get("market_group_map", {}),
        "watch_conditions_template": config.get("watch_conditions_template", {}),
        "exposure_matrix_details": config.get("exposure_matrix_details", []),
        "market_group_interpretation": config.get("market_group_interpretation", {}),
        "predictive_forecast": predictive_forecast,
        "analysis_generated_at": analysis_ts.isoformat(),
        "force_rebuild": force_rebuild,
        "alert_cluster_window_hours": ALERT_CLUSTER_WINDOW_HOURS,
        "alert_reignite_factor": ALERT_REIGNITE_INTENSITY_FACTOR,
        "realtime_mode": True,
        # Pro-grade analytical sections (rule-based, no LLM).
        "quantitative_evidence": quantitative_evidence,
        "systemic_fragility": systemic_fragility,
        "cascading_impacts": cascading_impacts,
        "tail_risk_scenarios": tail_risk_scenarios,
        "quantitative_evidence_matrix": quantitative_evidence_matrix,
        "spatial_contagion": spatial_contagion_payload,
    }

    context = sanitize_unicode_tree(context)

    return context

async def _get_macro_observations(
    db: AsyncSession,
    config: dict,
    lookback_days: int,
    notes: list,
    domain_id: str,
) -> List[dict]:
    """Fetch latest macro observations for domain + global core series."""
    s_data = config.get("structural_data", {})
    series_ids = (
        s_data.get("fred_series", [])
        + s_data.get("bls_series", [])
        + s_data.get("worldbank_indicators", [])
        + s_data.get("estat_series", [])
        + s_data.get("eia_series", [])
        + s_data.get("ecb_series", [])
        + s_data.get("bcb_series", [])
        + s_data.get("opec_series", [])
        + s_data.get("asean_series", [])
    )
    for core_id in get_core_global_series_ids():
        if core_id not in series_ids:
            series_ids.append(core_id)

    if not series_ids:
        return []

    results = []
    for s_id in series_ids:
        # Get latest observation
        stmt = select(ExternalObservation).where(
            ExternalObservation.series_id == s_id
        ).order_by(desc(ExternalObservation.date)).limit(1)
        
        obs_res = await db.execute(stmt)
        latest = obs_res.scalar_one_or_none()
        
        if not latest:
            notes.append(f"Macro series {s_id} not found in DB.")
            continue
            
        # Get previous observation for change calculation
        lookback_date = latest.date - timedelta(days=lookback_days)
        stmt_prev = select(ExternalObservation).where(
            ExternalObservation.series_id == s_id,
            ExternalObservation.date <= lookback_date
        ).order_by(desc(ExternalObservation.date)).limit(1)
        
        prev_res = await db.execute(stmt_prev)
        previous = prev_res.scalar_one_or_none()
        
        change_pct = None
        # `previous.value is not None` is load-bearing: None != 0 is True in Python,
        # so the prior `!= 0` test did NOT exclude a NULL. A NULL daily observation is
        # a real no-data day (FRED market holidays — DCOILWTICO/DGS10/DTWEXBGS/VIXCLS
        # all carry NULLs, most recently 2026-07-03), not a number. When it is NULL the
        # change was not measured, so change_pct stays None — never coerced to 0.
        if (
            previous
            and previous.value is not None
            and previous.value != 0
            and latest.value is not None
        ):
            change_pct = ((latest.value - previous.value) / abs(previous.value)) * 100

        results.append({
            "series_id": s_id,
            "source": latest.source,
            "latest_value": latest.value,
            "latest_date": latest.date.isoformat(),
            "previous_date": previous.date.isoformat() if previous else None,
            "span_days": (latest.date - previous.date).days if previous else None,
            "period_label": latest.period_label,
            "previous_value": previous.value if previous else None,
            "change_pct": change_pct,
            "raw_json": latest.raw_json
        })
        
    return results

async def _get_trade_flows(db: AsyncSession, config: dict, notes: list) -> List[dict]:
    """Fetch recent trade flows for commodity codes."""
    codes = config.get("structural_data", {}).get("comtrade_commodity_codes", [])
    if not codes:
        return []

    stmt = select(ExternalTradeFlow).where(
        ExternalTradeFlow.commodity_id.in_(codes)
    ).order_by(desc(ExternalTradeFlow.year), desc(ExternalTradeFlow.trade_value)).limit(20)
    
    res = await db.execute(stmt)
    flows = res.scalars().all()
    
    if not flows:
        notes.append(f"No trade flows found for codes: {codes}")
        
    # Filter and Deduplicate flows
    best_flows = {}
    for f in flows:
        if f.trade_value is None or f.trade_value < 100000:
            continue
            
        key = (f.reporter_name, f.partner_name, f.flow_type, f.commodity_id, f.year)
        # Since stmt is ordered by trade_value DESC, the first one we see for a key is the max
        if key not in best_flows:
            best_flows[key] = {
                "reporter_name": f.reporter_name,
                "partner_name": f.partner_name,
                "flow_type": f.flow_type,
                "commodity_id": f.commodity_id,
                "commodity_name": f.commodity_name,
                "year": f.year,
                "period": f.period,
                "trade_value": f.trade_value,
                "quantity": f.quantity,
                "unit": f.unit
            }
            
    return list(best_flows.values())

async def _get_industry_stats(db: AsyncSession, config: dict, notes: list) -> List[dict]:
    """Fetch latest industry/regional statistics."""
    # Logic to filter by relevant metrics for the domain could be added here
    # For now, we take latest stats from BEA/Census
    stmt = select(ExternalIndustryStat).order_by(
        desc(ExternalIndustryStat.year), 
        desc(ExternalIndustryStat.value)
    ).limit(20)
    
    res = await db.execute(stmt)
    stats = res.scalars().all()
    
    if not stats:
        notes.append("No industry stats found in DB.")

    # Filtering logic by domain keywords
    keywords = config.get("structural_data", {}).get("industry_keywords", [])
    
    results = []
    for s in stats:
        industry_name = s.industry_name or ""
        # If keywords are defined, we prioritize them. If not, we take everything.
        if keywords:
            if not any(k.lower() in industry_name.lower() for k in keywords):
                continue
        
        results.append({
            "source": s.source,
            "dataset": s.dataset,
            "geo_name": s.geo_name,
            "industry_name": s.industry_name,
            "metric_name": s.metric_name,
            "year": s.year,
            "value": s.value,
            "unit": s.unit
        })
        
    return results

async def _get_market_confirmation(db: AsyncSession, config: dict, lookback_days: int, notes: list) -> Dict[str, Any]:
    """Fetch latest market data and calculate price changes."""
    m_data = config.get("market_data", {})
    symbols = m_data.get("alpha_vantage_symbols", []) + m_data.get("frankfurter_fx_pairs", [])
    
    if not symbols:
        return {"instruments": [], "latest_prices": []}

    latest_prices = []
    
    for symbol in symbols:
        # Get latest price and join with instrument to get asset_class
        stmt = (
            select(MarketDataPrice, MarketDataInstrument.asset_class)
            .join(MarketDataInstrument, MarketDataPrice.instrument_id == MarketDataInstrument.id)
            .where(MarketDataPrice.symbol == symbol)
            .order_by(desc(MarketDataPrice.date))
            .limit(1)
        )
        
        res_price = await db.execute(stmt)
        row = res_price.one_or_none()
        
        if not row:
            notes.append(f"Market data for {symbol} not yet synced.")
            continue
            
        latest = row[0]
        asset_class = row[1]
            
        # Get previous price
        lookback_date = latest.date - timedelta(days=lookback_days)
        stmt_prev = select(MarketDataPrice).where(
            MarketDataPrice.symbol == symbol,
            MarketDataPrice.date <= lookback_date
        ).order_by(desc(MarketDataPrice.date)).limit(1)
        
        res_prev = await db.execute(stmt_prev)
        previous = res_prev.scalar_one_or_none()
        
        change_pct = None
        # Use close price for change calculation
        if latest.close is not None and previous and previous.close and previous.close != 0:
            change_pct = ((latest.close - previous.close) / previous.close) * 100
            
        latest_prices.append({
            "provider": latest.provider,
            "symbol": latest.symbol,
            "asset_class": asset_class or "unknown",
            "latest_date": latest.date.isoformat(),
            "latest_close": latest.close,
            "previous_date": previous.date.isoformat() if previous else None,
            "previous_close": previous.close if previous else None,
            "percent_change": change_pct,
            "interval": latest.interval
        })
        
    return {
        "latest_prices": latest_prices
    }

async def _complement_watch_indicators(db: AsyncSession, indicators: List[dict], notes: list) -> List[dict]:
    """Add latest database values to watch indicator definitions."""
    results = []
    for ind in indicators:
        comp_ind = ind.copy()
        l_type = ind.get("lookup_type")
        s_id = ind.get("series_id") or ind.get("symbol")
        
        latest_val = None
        if l_type == "external_observation":
            stmt = select(ExternalObservation.value).where(
                ExternalObservation.series_id == s_id
            ).order_by(desc(ExternalObservation.date)).limit(1)
            latest_val = (await db.execute(stmt)).scalar_one_or_none()
        elif l_type == "trade_flow":
            stmt = select(ExternalTradeFlow.trade_value).where(
                ExternalTradeFlow.commodity_id == s_id
            ).order_by(desc(ExternalTradeFlow.year)).limit(1)
            latest_val = (await db.execute(stmt)).scalar_one_or_none()
        elif l_type == "market_price":
            stmt = select(MarketDataPrice.close).where(
                MarketDataPrice.symbol == s_id
            ).order_by(desc(MarketDataPrice.date)).limit(1)
            latest_val = (await db.execute(stmt)).scalar_one_or_none()
            
        comp_ind["latest_value"] = latest_val
        results.append(comp_ind)
        
    return results

def _calculate_freshness(structural: dict, market: dict) -> Dict[str, str]:
    """Identify the most recent data timestamps."""
    all_dates = []
    for obs in structural.get("macro_observations", []):
        if obs.get("latest_date"): all_dates.append(obs["latest_date"])
    for price in market.get("latest_prices", []):
        if price.get("latest_date"): all_dates.append(price["latest_date"])
        
    if not all_dates:
        return {"last_update": None}
        
    return {"last_update": max(all_dates)}

def _topic_match_keywords(
    domain_id: str, topic: Optional[str], trigger_label: Optional[str]
) -> Set[str]:
    """Keywords for matching related alerts in the same narrative thread."""
    keywords: Set[str] = set()
    for token in re.split(r"[_\s\-]+", domain_id or ""):
        if len(token) >= 4:
            keywords.add(token.lower())
    for token in re.split(r"[_\s\-]+", topic or ""):
        if len(token) >= 4:
            keywords.add(token.lower())
    if trigger_label:
        for token in re.findall(r"[A-Za-z]{4,}", trigger_label):
            keywords.add(token.lower())
    return keywords


def _alert_matches_domain_context(
    row: AlertLog, domain_id: str, keywords: Set[str]
) -> bool:
    row_domain = infer_domain_from_topic(row.topic or "")
    if row_domain == domain_id or (row.topic or "") == domain_id:
        return True
    label = (row.target_label or "").lower()
    return bool(keywords) and any(kw in label for kw in keywords)


def _first_evidence_url(meta: Optional[dict]) -> Optional[str]:
    """Primary external URL from alert metadata evidence_list."""
    if not meta:
        return None
    for item in meta.get("evidence_list") or []:
        url = item.get("url") or item.get("link") or item.get("source_url")
        if url and str(url).strip():
            return str(url).strip()
    return None


def _related_news_from_evidence(meta: Optional[dict]) -> list:
    """
    Pro-owned related-news extraction sourced from the alert's own
    ``evidence_list`` (core alert metadata). Replaces the former dependency on
    the deprecated ``free_alert`` payload; normalises each evidence item to the
    {title, source, category, published, url} shape the downstream relevance
    filter and LLM shaper expect.
    """
    if not meta:
        return []
    out = []
    for ev in meta.get("evidence_list") or []:
        if not isinstance(ev, dict):
            continue
        out.append({
            "title": ev.get("title") or ev.get("headline") or "",
            "source": ev.get("source") or ev.get("domain") or ev.get("type") or "OSINT",
            "category": ev.get("category") or ev.get("rough_category") or "general",
            "published": ev.get("published") or ev.get("published_at") or "",
            "url": ev.get("url") or ev.get("link") or ev.get("source_url"),
        })
    return out


async def _fetch_related_alert_events(
    db: AsyncSession,
    alert_log: Optional[AlertLog],
    domain_id: str,
    notes: list,
    *,
    limit: int = 8,
    lookback_days: Optional[int] = None,
    window_hours: Optional[int] = None,
    vocabulary: Optional[Dict[str, Any]] = None,
    trigger_tokens: Optional[Set[str]] = None,
) -> List[dict]:
    """
    Alerts in the same domain / topic keyword thread (24h cluster window by default).
    """
    if window_hours is not None:
        since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    else:
        days = lookback_days if lookback_days is not None else 1
        since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(AlertLog)
        .where(
            AlertLog.triggered_at >= since,
            AlertLog.suppressed == False,  # noqa: E712
        )
        .order_by(desc(AlertLog.triggered_at), desc(AlertLog.intelligence_score))
        .limit(120)
    )
    rows = (await db.execute(stmt)).scalars().all()

    trigger_label = alert_log.target_label if alert_log else None
    trigger_topic = alert_log.topic if alert_log else None
    keywords = _topic_match_keywords(domain_id, trigger_topic, trigger_label)
    current_id = str(alert_log.id) if alert_log else None

    vocab = vocabulary or build_sector_vocabulary(
        get_pro_domain_config(domain_id) or {}, {}
    )
    t_tokens = trigger_tokens or set()

    matched: List[AlertLog] = []
    for row in rows:
        if not _alert_matches_domain_context(row, domain_id, keywords):
            continue
        label = sanitize_unicode_text(row.target_label or "")
        score = structural_correlation_score(label, vocab, trigger_tokens=t_tokens)
        if infer_domain_from_topic(row.topic or "") == domain_id:
            score = max(score, 0.55)
        if score < MIN_ALERT_CORRELATION:
            continue
        matched.append(row)

    # Ensure trigger alert is included and first in timeline ordering later
    if alert_log and all(str(a.id) != current_id for a in matched):
        matched.insert(0, alert_log)

    matched.sort(
        key=lambda a: (a.intelligence_score or 0.0, a.triggered_at or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )
    selected: List[AlertLog] = []
    if alert_log:
        selected.append(alert_log)
    for row in matched:
        if alert_log and str(row.id) == current_id:
            continue
        selected.append(row)
        if len(selected) >= limit:
            break

    events: List[dict] = []
    for row in selected:
        row_meta = row.metadata_json or {}
        events.append(
            {
                "alert_id": str(row.id),
                "title": sanitize_unicode_text((row.target_label or "")[:200]),
                "topic": row.topic,
                "severity": row.severity,
                "trigger_type": row.trigger_type,
                "intensity": row.intensity,
                "intelligence_score": row.intelligence_score,
                "fidelity_score": row.fidelity_score,
                "timestamp": row.triggered_at.isoformat() if row.triggered_at else None,
                "source": "alert_log",
                "location_label": None,
                "source_url": _first_evidence_url(row_meta),
            }
        )

    window_label = (
        f"{window_hours}h"
        if window_hours is not None
        else f"{lookback_days or 1}d"
    )
    if not events and alert_log:
        notes.append(f"No related domain alerts in the last {window_label} besides the trigger.")
    elif len(events) < 2:
        notes.append(f"Limited related alert history in the last {window_label}.")

    return events


def _build_event_timeline(
    related_news: List[dict],
    signal_ctx: Optional[dict],
    *,
    related_events: Optional[List[dict]] = None,
    vocabulary: Optional[Dict[str, Any]] = None,
    trigger_tokens: Optional[Set[str]] = None,
) -> List[dict]:
    """
    Merge related AlertLog events and news evidence into one chronological timeline.
    """
    raw: List[dict] = []

    vocab = vocabulary or {"phrases": set(), "series_ids": set()}
    t_tokens = trigger_tokens or set()

    for ev in related_events or []:
        title = sanitize_unicode_text(ev.get("title") or "")
        coeff = structural_correlation_score(title, vocab, trigger_tokens=t_tokens)
        if ev.get("alert_id") == (signal_ctx or {}).get("alert_id"):
            coeff = max(coeff, 1.0)
        raw.append(
            {
                "timestamp": ev.get("timestamp"),
                "title": title,
                "source_url": ev.get("source_url"),
                "location_label": ev.get("location_label"),
                "alert_id": ev.get("alert_id"),
                "severity": ev.get("severity"),
                "trigger_type": ev.get("trigger_type"),
                "intensity": ev.get("intensity"),
                "intelligence_score": ev.get("intelligence_score"),
                "fidelity_score": ev.get("fidelity_score"),
                "source": ev.get("source", "alert_log"),
                "structural_correlation": round(coeff, 3),
            }
        )

    seen_titles: Set[str] = {r["title"].lower() for r in raw if r.get("title")}

    _MARKET_KW = {"market", "stock", "etf", "bond", "yield", "price", "rally", "crash", "surge", "plunge", "trading"}
    _CONFIRM_KW = {"confirm", "verify", "report", "official", "statement", "announce"}

    for item in related_news[:5]:
        title = sanitize_unicode_text(
            (item.get("title") or item.get("headline") or item.get("text", "") or "")[:200]
        )
        coeff = structural_correlation_score(title, vocab, trigger_tokens=t_tokens)
        if coeff < MIN_NEWS_CORRELATION:
            continue
        if title.lower() in seen_titles:
            continue
        source_url = item.get("url") or item.get("source_url") or item.get("link", "")
        timestamp = item.get("published") or item.get("timestamp") or item.get("date")
        location_label = item.get("location") or item.get("country") or None
        title_lower = title.lower()
        if any(kw in title_lower for kw in _MARKET_KW):
            role = "market_reaction"
        elif any(kw in title_lower for kw in _CONFIRM_KW):
            role = "confirmation"
        else:
            role = "context"
        raw.append(
            {
                "timestamp": timestamp,
                "title": title,
                "alert_id": None,
                "source_url": (str(source_url).strip() if source_url else None) or None,
                "location_label": location_label,
                "source": "news",
                "role": role,
                "structural_correlation": round(coeff, 3),
            }
        )
        seen_titles.add(title.lower())

    def _sort_key(item: dict) -> tuple:
        ts = item.get("timestamp")
        if ts:
            return (0, str(ts))
        return (1, "")

    raw.sort(key=_sort_key)

    trigger_alert_id = (signal_ctx or {}).get("alert_id")
    typed = _assign_timeline_types(raw, trigger_alert_id)
    return filter_correlated_timeline_events(typed)


def _assign_timeline_types(timeline: List[dict], trigger_alert_id: Optional[str]) -> List[dict]:
    """Map entries to UI types: trigger, context, background."""
    if not timeline:
        return []

    for item in timeline:
        if trigger_alert_id and item.get("alert_id") == trigger_alert_id:
            item["type"] = "trigger"
            item["role"] = "trigger"
        elif item.get("role") in ("background", "trigger", "context", "market_reaction", "confirmation"):
            role = item["role"]
            if role in ("market_reaction", "confirmation"):
                item["type"] = "context"
            elif role == "background":
                item["type"] = "background"
            else:
                item["type"] = role
        else:
            item["type"] = None

    non_trigger_idxs = [
        i for i, item in enumerate(timeline) if item.get("type") not in ("trigger",)
    ]
    if not non_trigger_idxs:
        return timeline

    if len(non_trigger_idxs) == 1:
        timeline[non_trigger_idxs[0]]["type"] = "context"
        timeline[non_trigger_idxs[0]]["role"] = "context"
    else:
        first_i = non_trigger_idxs[0]
        timeline[first_i]["type"] = "background"
        timeline[first_i]["role"] = "background"
        for i in non_trigger_idxs[1:]:
            if timeline[i].get("type") is None:
                timeline[i]["type"] = "context"
                timeline[i]["role"] = "context"

    return timeline

