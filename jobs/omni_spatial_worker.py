"""
Phase 7.2 — Omni-Domain Spatial Worker.

Every ~5 minutes (via ``main_scheduler``):
  1. Load recent ``AlertLog`` rows (24h rolling window).
  2. Resolve coordinates with offline ``GeoLocator`` (no external APIs).
  3. Run ``SpatialPhysicsEngine`` for global / energy / shipping domains.
  4. Cleanup-First overwrite of ``spatial_nodes`` and ``spatial_edges``.
  5. Append a ``ContagionHistory`` snapshot per domain (Time Machine).
  6. Purge ``ContagionHistory`` rows older than 24h (rolling retention).

Run manually:

    python -m jobs.omni_spatial_worker
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.pro_domain_config import infer_domain_from_topic
from analysis.pro_geo_locator import GeoLocator
from analysis.spatial_physics_engine import (
    OMNI_SPATIAL_DOMAINS,
    ComputedSpatialEdge,
    ComputedSpatialNode,
    DomainSpatialGraph,
    SpatialPhysicsEngine,
    _keyword_hits,
    prior_entropy_index_map,
)
from db.database import AsyncSessionLocal
from db.models import AlertLog, ContagionHistory, SpatialEdge, SpatialNode

logger = logging.getLogger(__name__)

WINDOW_HOURS = 24.0


def _alert_text_bundle(alert: AlertLog) -> str:
    parts: List[str] = [str(alert.target_label or "")]
    meta = alert.metadata_json
    if isinstance(meta, dict):
        for key in ("location_label", "headline", "title", "summary", "cluster_label"):
            val = meta.get(key)
            if val:
                parts.append(str(val))
    return " ".join(parts)


def resolve_alert_coordinates(
    alert: AlertLog,
    geo: GeoLocator,
) -> Optional[Tuple[float, float, str]]:
    """Return (lat, lon, label) or None when no offline resolution is possible."""
    if alert.location_lat is not None and alert.location_lng is not None:
        try:
            lat = float(alert.location_lat)
            lon = float(alert.location_lng)
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon, str(alert.target_label or "")
        except (TypeError, ValueError):
            pass

    bundle = _alert_text_bundle(alert)
    for kw in _keyword_hits(bundle):
        hit = geo.get_coordinates(kw)
        if hit:
            return float(hit["lat"]), float(hit["lon"]), str(hit.get("name") or kw)

    for raw in (alert.target_label, bundle):
        if not raw or len(str(raw).strip()) < 3:
            continue
        hit = geo.get_coordinates(str(raw).strip())
        if hit:
            return float(hit["lat"]), float(hit["lon"]), str(hit.get("name") or raw)

    return None


def _node_payload(n: ComputedSpatialNode, node_id: str, domain_id: str) -> Dict[str, Any]:
    return {
        "id": node_id,
        "domain_id": domain_id,
        "name": n.name,
        "lat": n.lat,
        "lon": n.lon,
        "impact_score": n.impact_score,
        "entropy_index": n.entropy_index,
        "type": "epicenter" if n.is_epicenter else "affected",
    }


def _edge_payload(e: ComputedSpatialEdge, edge_id: str, domain_id: str) -> Dict[str, Any]:
    return {
        "id": edge_id,
        "domain_id": domain_id,
        "source_lat": e.source_lat,
        "source_lon": e.source_lon,
        "target_lat": e.target_lat,
        "target_lon": e.target_lon,
        "intensity": e.edge_intensity,
        "edge_intensity": e.edge_intensity,
        "viscosity_coefficient": e.viscosity_coefficient,
        "order_level": e.order_level,
        "target_order": e.order_level,
    }


def graph_to_orm(
    graph: DomainSpatialGraph,
) -> Tuple[List[SpatialNode], List[SpatialEdge], Dict[str, Any], Dict[str, Any]]:
    """Convert computed graph → ORM rows + JSONB payloads for history."""
    nodes: List[SpatialNode] = []
    edges: List[SpatialEdge] = []
    node_payloads: List[Dict[str, Any]] = []
    edge_payloads: List[Dict[str, Any]] = []

    for cn in graph.nodes:
        nid = uuid.uuid4()
        orm = SpatialNode(
            id=nid,
            domain_id=graph.domain_id,
            name=cn.name,
            lat=cn.lat,
            lon=cn.lon,
            impact_score=cn.impact_score,
            entropy_index=cn.entropy_index,
            is_epicenter=cn.is_epicenter,
        )
        nodes.append(orm)
        node_payloads.append(_node_payload(cn, str(nid), graph.domain_id))

    for ce in graph.edges:
        eid = uuid.uuid4()
        orm = SpatialEdge(
            id=eid,
            domain_id=graph.domain_id,
            source_lat=ce.source_lat,
            source_lon=ce.source_lon,
            target_lat=ce.target_lat,
            target_lon=ce.target_lon,
            edge_intensity=ce.edge_intensity,
            viscosity_coefficient=ce.viscosity_coefficient,
            order_level=ce.order_level,
        )
        edges.append(orm)
        edge_payloads.append(_edge_payload(ce, str(eid), graph.domain_id))

    return nodes, edges, node_payloads, edge_payloads


async def fetch_recent_alerts(session: AsyncSession, *, hours: float = WINDOW_HOURS) -> List[AlertLog]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await session.execute(
        select(AlertLog)
        .where(
            AlertLog.triggered_at >= cutoff,
            AlertLog.suppressed.is_(False),
        )
        .order_by(AlertLog.triggered_at.desc())
    )
    return list(result.scalars().all())


async def load_existing_nodes(session: AsyncSession) -> List[SpatialNode]:
    result = await session.execute(
        select(SpatialNode).where(SpatialNode.domain_id.in_(OMNI_SPATIAL_DOMAINS))
    )
    return list(result.scalars().all())


async def persist_domain_graph(
    session: AsyncSession,
    graph: DomainSpatialGraph,
    *,
    snapshot_ts: datetime,
) -> Dict[str, int]:
    nodes, edges, node_payloads, edge_payloads = graph_to_orm(graph)

    for n in nodes:
        session.add(n)
    for e in edges:
        session.add(e)

    history = ContagionHistory(
        id=uuid.uuid4(),
        domain_id=graph.domain_id,
        snapshot_timestamp=snapshot_ts,
        nodes_payload=node_payloads,
        edges_payload=edge_payloads,
        entropy_index=graph.mean_entropy,
        viscosity_coefficient=graph.mean_viscosity,
        phase_transition_warning=graph.phase_transition_warning,
    )
    session.add(history)

    return {"nodes": len(nodes), "edges": len(edges)}


async def run_omni_spatial_worker(session: Optional[AsyncSession] = None) -> Dict[str, Any]:
    """
    Main entry — safe to call from scheduler or CLI.
    Returns a summary dict for logging.
    """
    owns_session = session is None
    if owns_session:
        session = AsyncSessionLocal()

    summary: Dict[str, Any] = {
        "alerts_scanned": 0,
        "events_geocoded": 0,
        "domains": {},
        "status": "ok",
    }

    try:
        assert session is not None
        prior_rows = await load_existing_nodes(session)
        prior_entropy = prior_entropy_index_map(prior_rows)

        alerts = await fetch_recent_alerts(session)
        summary["alerts_scanned"] = len(alerts)

        try:
            geo = GeoLocator()
        except FileNotFoundError as exc:
            logger.error("Geo DB missing — spatial worker aborted: %s", exc)
            summary["status"] = "geo_db_missing"
            return summary

        engine = SpatialPhysicsEngine(window_hours=WINDOW_HOURS)
        events_by_domain: Dict[str, List] = {d: [] for d in OMNI_SPATIAL_DOMAINS}

        for alert in alerts:
            pro_domain = infer_domain_from_topic(alert.topic or "")
            coords = resolve_alert_coordinates(alert, geo)
            if not coords:
                continue
            lat, lon, label = coords
            ev = engine.normalize_alert(
                alert,
                pro_domain_id=pro_domain,
                lat=lat,
                lon=lon,
                label=label,
            )
            if not ev:
                continue
            summary["events_geocoded"] += 1
            omni = ev.domain_id
            if omni in events_by_domain:
                events_by_domain[omni].append(ev)
            events_by_domain["global"].append(ev)

        graphs: List[DomainSpatialGraph] = []
        for domain_id in OMNI_SPATIAL_DOMAINS:
            g = engine.build_domain_graph(
                domain_id,
                events_by_domain.get(domain_id, []),
                prior_nodes=prior_entropy,
            )
            graphs.append(g)

        # Cleanup-First: active spatial tables only (history is append-only).
        await session.execute(
            delete(SpatialEdge).where(SpatialEdge.domain_id.in_(OMNI_SPATIAL_DOMAINS))
        )
        await session.execute(
            delete(SpatialNode).where(SpatialNode.domain_id.in_(OMNI_SPATIAL_DOMAINS))
        )

        now = datetime.now(timezone.utc)
        for graph in graphs:
            counts = await persist_domain_graph(session, graph, snapshot_ts=now)
            summary["domains"][graph.domain_id] = counts

        await session.commit()

        # ── 24-hour rolling retention (Time Machine window) ──────────────────
        # Any ContagionHistory snapshot older than 24 hours is permanently
        # outside the frontend slider range and serves no analytical purpose.
        # Delete in a dedicated transaction so a purge failure never rolls back
        # the freshly committed snapshot above.
        history_cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        purge_result = await session.execute(
            delete(ContagionHistory).where(
                ContagionHistory.snapshot_timestamp < history_cutoff
            )
        )
        await session.commit()
        purged = purge_result.rowcount if purge_result.rowcount is not None else 0
        summary["history_purged"] = purged
        if purged:
            logger.info("ContagionHistory: purged %d rows older than 24h.", purged)

        logger.info(
            "Omni spatial worker: alerts=%s geocoded=%s domains=%s purged_history=%s",
            summary["alerts_scanned"],
            summary["events_geocoded"],
            summary["domains"],
            purged,
        )
    except Exception:
        await session.rollback()
        logger.exception("Omni spatial worker failed")
        summary["status"] = "error"
        raise
    finally:
        if owns_session:
            await session.close()

    return summary


async def _main() -> None:
    async with AsyncSessionLocal() as session:
        result = await run_omni_spatial_worker(session)
    print(result)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
