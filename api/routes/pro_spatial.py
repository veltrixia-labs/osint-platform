"""
Phase 7.1 — Dedicated Spatial Engine API.

Backed by the new `spatial_nodes`, `spatial_edges`, and `contagion_history`
tables (db/models.py). Independent of the Pro report generation cycle so
the dashboard Omni-Domain monitor can poll fresh state every few seconds
without waiting on a 30-minute report regen.

Endpoints
─────────
  GET /api/pro/domains/global/spatial-contagion
      → live nodes/edges for the 'global' aggregate (or merged from all
        per-domain rows if no 'global' row exists).

  GET /api/pro/domains/{domain_id}/fragility-history?days=N
      → last 24h of ContagionHistory snapshots for `domain_id`, plus the
        single most-recent spatial graph as `latest_spatial_contagion`.

Both endpoints are gated to Pro / Experts / Enterprise tiers and return
no-store headers so the polling client always sees fresh data.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.database import AsyncSessionLocal
from db.models import SpatialNode, SpatialEdge, ContagionHistory
from api.gating import (
    get_effective_tier,
    TIER_PRO,
    TIER_EXPERTS,
    TIER_ENTERPRISE,
)
from api.auth import get_optional_current_user

router = APIRouter(prefix="/pro", tags=["Pro Spatial"])

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}

# Same hard cap as the legacy fragility-history endpoint so a hostile client
# can't sweep the entire ContagionHistory table with `days=9999`.
_MAX_HISTORY_DAYS = 90

_ALLOWED_TIERS = {TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE}


async def _get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def _get_current_tier(
    current_user: Optional[Any] = Depends(get_optional_current_user),
) -> str:
    user = None
    if current_user is not None:
        user = current_user[0] if isinstance(current_user, tuple) else current_user
    return await get_effective_tier(user)


def _require_pro(tier: str, detail: str) -> None:
    if tier not in _ALLOWED_TIERS:
        raise HTTPException(status_code=403, detail=detail)


def _node_to_dict(n: SpatialNode) -> Dict[str, Any]:
    """Serialise a SpatialNode row to the frontend's expected shape."""
    return {
        "id": str(n.id),
        "domain_id": n.domain_id,
        "name": n.name,
        "lat": float(n.lat),
        "lon": float(n.lon),
        "impact_score": float(n.impact_score),
        "entropy_index": float(n.entropy_index),
        "type": "epicenter" if n.is_epicenter else "affected",
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


def _edge_to_dict(e: SpatialEdge) -> Dict[str, Any]:
    return {
        "id": str(e.id),
        "domain_id": e.domain_id,
        "source_lon": float(e.source_lon),
        "source_lat": float(e.source_lat),
        "target_lon": float(e.target_lon),
        "target_lat": float(e.target_lat),
        "intensity": float(e.edge_intensity),
        "edge_intensity": float(e.edge_intensity),
        "viscosity_coefficient": float(e.viscosity_coefficient),
        "order_level": int(e.order_level),
        # alias kept for frontend's ResolvedEdge.target_order mapping
        "target_order": int(e.order_level),
    }


def _shape_contagion_payload(
    domain_id: str,
    nodes: List[SpatialNode],
    edges: List[SpatialEdge],
) -> Dict[str, Any]:
    """Build the {nodes, edges, epicenter_impact_score, ...} dict the
    frontend's SpatialContagion type already understands."""
    serialised_nodes = [_node_to_dict(n) for n in nodes]
    serialised_edges = [_edge_to_dict(e) for e in edges]

    epicenter_impact = 0.0
    intensity_sum = 0.0
    order_counts = {1: 0, 2: 0, 3: 0}
    for n in nodes:
        if n.impact_score > epicenter_impact:
            epicenter_impact = float(n.impact_score)
    for e in edges:
        intensity_sum += float(e.edge_intensity)
        if e.order_level in order_counts:
            order_counts[e.order_level] += 1

    return {
        "domain_id": domain_id,
        "nodes": serialised_nodes,
        "edges": serialised_edges,
        "epicenter_impact_score": epicenter_impact,
        "edge_intensity": (intensity_sum / len(edges)) if edges else 0.0,
        "node_count": len(serialised_nodes),
        "edge_count": len(serialised_edges),
        "order_counts": {
            "order_1": order_counts[1],
            "order_2": order_counts[2],
            "order_3": order_counts[3],
        },
        "schema_version": "spatial_engine_v1",
    }


@router.get("/domains/global/spatial-contagion")
async def get_global_spatial_contagion(
    response: Response,
    db: AsyncSession = Depends(_get_db),
    tier: str = Depends(_get_current_tier),
):
    """
    Return the cross-domain Omni-Monitor view.

    Strategy:
      1. If at least one row has `domain_id='global'`, return that directly
         (the spatial-engine job has produced an explicit aggregate).
      2. Otherwise, merge every non-'global' domain into a synthetic
         aggregate. Cheap because we already have indexes on domain_id.
    """
    _require_pro(tier, "Pro subscription required for spatial contagion.")
    for k, v in _NO_STORE_HEADERS.items():
        response.headers[k] = v

    explicit_nodes = (
        await db.execute(
            select(SpatialNode).where(SpatialNode.domain_id == "global")
        )
    ).scalars().all()

    if explicit_nodes:
        explicit_edges = (
            await db.execute(
                select(SpatialEdge).where(SpatialEdge.domain_id == "global")
            )
        ).scalars().all()
        return _shape_contagion_payload("global", list(explicit_nodes), list(explicit_edges))

    # Aggregate path — fold every per-domain row into one payload.
    all_nodes = (
        await db.execute(
            select(SpatialNode).where(SpatialNode.domain_id != "global")
        )
    ).scalars().all()
    all_edges = (
        await db.execute(
            select(SpatialEdge).where(SpatialEdge.domain_id != "global")
        )
    ).scalars().all()
    return _shape_contagion_payload("global", list(all_nodes), list(all_edges))


def _snapshot_to_series_point(snap: ContagionHistory) -> Dict[str, Any]:
    """Serialise one ContagionHistory row to the frontend series schema."""
    return {
        "timestamp": snap.snapshot_timestamp.isoformat() if snap.snapshot_timestamp else None,
        "entropy_index": round(float(snap.entropy_index), 4),
        "viscosity_coefficient": round(float(snap.viscosity_coefficient), 4),
        "label": "WARN" if snap.phase_transition_warning else "OK",
        "phase_transition_warning": bool(snap.phase_transition_warning),
        "sample_size": (
            len(snap.nodes_payload) if isinstance(snap.nodes_payload, list) else 0
        ),
    }


async def _aggregate_global_series(
    db: AsyncSession, since: datetime
) -> List[Dict[str, Any]]:
    """
    Synthesise a 'global' fragility timeline by folding every per-domain
    ContagionHistory row into one point per ``snapshot_timestamp``.

    Used only when the omni worker has NOT written explicit ``domain_id='global'``
    snapshots (e.g. an older worker build). Because the worker stamps every
    domain in a cycle with the same ``snapshot_timestamp``, grouping on that
    column cleanly buckets each cycle. We average entropy/viscosity across the
    cycle's domains and OR the phase-transition warnings, so the aggregate
    timeline behaves like a real per-domain one for the slider/play loop.
    """
    rows = (
        await db.execute(
            select(ContagionHistory)
            .where(
                ContagionHistory.domain_id != "global",
                ContagionHistory.snapshot_timestamp >= since,
            )
            .order_by(ContagionHistory.snapshot_timestamp.asc())
        )
    ).scalars().all()

    buckets: Dict[Any, Dict[str, Any]] = {}
    for snap in rows:
        ts = snap.snapshot_timestamp
        if ts is None:
            continue
        b = buckets.get(ts)
        if b is None:
            b = {
                "timestamp": ts,
                "entropy_sum": 0.0,
                "viscosity_sum": 0.0,
                "count": 0,
                "warning": False,
                "sample_size": 0,
            }
            buckets[ts] = b
        b["entropy_sum"] += float(snap.entropy_index)
        b["viscosity_sum"] += float(snap.viscosity_coefficient)
        b["count"] += 1
        b["warning"] = b["warning"] or bool(snap.phase_transition_warning)
        if isinstance(snap.nodes_payload, list):
            b["sample_size"] += len(snap.nodes_payload)

    series: List[Dict[str, Any]] = []
    for ts in sorted(buckets.keys()):
        b = buckets[ts]
        n = max(1, b["count"])
        series.append({
            "timestamp": ts.isoformat(),
            "entropy_index": round(b["entropy_sum"] / n, 4),
            "viscosity_coefficient": round(b["viscosity_sum"] / n, 4),
            "label": "WARN" if b["warning"] else "OK",
            "phase_transition_warning": bool(b["warning"]),
            "sample_size": b["sample_size"],
        })
    return series


@router.get("/domains/{domain_id}/fragility-history")
async def get_fragility_history(
    domain_id: str,
    response: Response,
    days: int = Query(1, ge=1, le=_MAX_HISTORY_DAYS),
    db: AsyncSession = Depends(_get_db),
    tier: str = Depends(_get_current_tier),
):
    """
    Return up to ``days`` worth of ContagionHistory snapshots for a domain,
    ASC by timestamp so the Time Machine slider can scrub left→right.

    Response shape matches the legacy pro_reports.fragility-history endpoint
    so the frontend SurveillanceMapController works unchanged:

        {
          domain_id, days, count, warning_count, last_point,
          series: [ { timestamp, entropy_index, viscosity_coefficient,
                      label, phase_transition_warning, sample_size }, ... ],
          latest_spatial_contagion: { nodes, edges, ... } | None
        }
    """
    _require_pro(tier, "Pro subscription required for fragility history.")
    for k, v in _NO_STORE_HEADERS.items():
        response.headers[k] = v

    domain = (domain_id or "").strip()
    if not domain:
        raise HTTPException(status_code=400, detail="domain_id is required")

    since = datetime.now(timezone.utc) - timedelta(days=int(days))

    snapshots = (
        await db.execute(
            select(ContagionHistory)
            .where(
                ContagionHistory.domain_id == domain,
                ContagionHistory.snapshot_timestamp >= since,
            )
            .order_by(ContagionHistory.snapshot_timestamp.asc())
        )
    ).scalars().all()

    series: List[Dict[str, Any]] = [_snapshot_to_series_point(s) for s in snapshots]

    # Global fallback — if the worker hasn't written explicit 'global'
    # snapshots, fold the per-domain timeline into a synthetic aggregate so
    # the Time Machine slider for the default Omni view is never empty.
    if domain == "global" and not series:
        series = await _aggregate_global_series(db, since)

    warning_count = sum(1 for p in series if p["phase_transition_warning"])
    last_point = series[-1] if series else None

    # Latest live spatial graph for the domain — pulled from spatial_nodes
    # / spatial_edges (not the history blob), so it always reflects the
    # absolute newest computation cycle even between snapshot writes.
    live_nodes = (
        await db.execute(
            select(SpatialNode).where(SpatialNode.domain_id == domain)
        )
    ).scalars().all()
    live_edges = (
        await db.execute(
            select(SpatialEdge).where(SpatialEdge.domain_id == domain)
        )
    ).scalars().all()

    latest_spatial = None
    if live_nodes:
        latest_spatial = _shape_contagion_payload(domain, list(live_nodes), list(live_edges))
    elif snapshots:
        # Cold-state fallback: rehydrate from the newest history snapshot.
        newest = snapshots[-1]
        latest_spatial = {
            "domain_id": domain,
            "nodes": newest.nodes_payload or [],
            "edges": newest.edges_payload or [],
            "epicenter_impact_score": max(
                (float(n.get("impact_score", 0)) for n in (newest.nodes_payload or [])),
                default=0.0,
            ),
            "edge_intensity": 0.0,
            "schema_version": "spatial_engine_v1_history_replay",
        }

    return {
        "domain_id": domain,
        "days": int(days),
        "count": len(series),
        "warning_count": warning_count,
        "last_point": last_point,
        "series": series,
        "latest_spatial_contagion": latest_spatial,
    }
