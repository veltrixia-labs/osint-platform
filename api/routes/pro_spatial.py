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

import glob
import json
import logging
import os
import re
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

logger = logging.getLogger(__name__)

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


def _nullable_float(v: Optional[float]) -> Optional[float]:
    """
    None survives as None. An UNMEASURED magnitude is not zero.

    `float(None)` raises TypeError, and coercing None -> 0.0 would assert
    "no impact" about something we never measured. The renderer already speaks
    this dialect: a null impact_score / intensity drives the `exposed_unquantified`
    hollow-grey path (see pro_interactive_map.ts, fedd638).
    """
    return None if v is None else float(v)


def _node_to_dict(n: SpatialNode) -> Dict[str, Any]:
    """Serialise a SpatialNode row to the frontend's expected shape."""
    return {
        # Prefer the vault canonical id (the edge join key). Falls back to the row
        # UUID, which is byte-identical to the previous behaviour while node_id is
        # NULL — i.e. for every row written by the existing engine.
        "id": n.node_id or str(n.id),
        "domain_id": n.domain_id,
        "name": n.name,
        "lat": float(n.lat),
        "lon": float(n.lon),
        "impact_score": _nullable_float(n.impact_score),
        "entropy_index": float(n.entropy_index),
        # node_type is the source of truth; is_epicenter is the back-compat fallback.
        "type": n.node_type or ("epicenter" if n.is_epicenter else "affected"),
        "country": n.country,
        "order": n.order_level,
        "confidence": n.confidence,
        "why": n.why,
        "has_unquantified_direct_edge": bool(n.has_unquantified_direct_edge),
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


def _edge_to_dict(e: SpatialEdge) -> Dict[str, Any]:
    intensity = _nullable_float(e.edge_intensity)
    return {
        "id": str(e.id),
        "domain_id": e.domain_id,
        "source_lon": float(e.source_lon),
        "source_lat": float(e.source_lat),
        "target_lon": float(e.target_lon),
        "target_lat": float(e.target_lat),
        "intensity": intensity,
        "edge_intensity": intensity,
        # Explicit flag: unknown, not zero. Denormalised so the renderer never has
        # to infer intent from a null.
        "unquantified": bool(e.unquantified),
        "source_id": e.source_node_id,
        "target_id": e.target_node_id,
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

    # ── Aggregates EXCLUDE unmeasured magnitudes ─────────────────────────────
    # An unmeasured node must not be mistaken for the colour-ramp denominator, and
    # an unmeasured edge must not dilute the mean. Note the DIVISOR changes too:
    # we average over the edges actually summed, not over every edge.
    measured_scores = [float(n.impact_score) for n in nodes if n.impact_score is not None]
    measured_intensities = [
        float(e.edge_intensity) for e in edges if e.edge_intensity is not None
    ]

    if measured_scores:
        epicenter_impact = max(measured_scores)
    elif nodes:
        # Nodes exist but every magnitude is unmeasured. The renderer divides by
        # this value (`t = impact_score / epicenter_impact_score`), so it must never
        # be 0 -> use a 1.0 sentinel rather than a divide-by-zero.
        epicenter_impact = 1.0
    else:
        # No nodes at all — preserve the existing 0.0 (the frontend's
        # `epicenter_impact_score || 100` fallback depends on this being falsy).
        epicenter_impact = 0.0

    mean_intensity = (
        sum(measured_intensities) / len(measured_intensities)
        if measured_intensities
        else 0.0
    )

    order_counts = {1: 0, 2: 0, 3: 0}
    for e in edges:
        if e.order_level in order_counts:
            order_counts[e.order_level] += 1

    return {
        "domain_id": domain_id,
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


# ── Scenario catalogue ───────────────────────────────────────────────────────
#
# Read from data/scenarios/*.json rather than SELECT DISTINCT domain_id, which
# would be brittle (a LIKE 'strait_%' prefix match is not a schema) and would show
# nothing until the loader has run. The files ARE the catalogue.
_SCENARIO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "scenarios",
)
_scenario_cache: Optional[List[Dict[str, Any]]] = None


def _slugify_hub(hub: str) -> str:
    """Must match jobs.load_scenarios.slugify_hub — this is the domain_id."""
    return re.sub(r"[^a-z0-9_]+", "_", (hub or "").strip().lower()).strip("_")


def _load_scenario_catalogue() -> List[Dict[str, Any]]:
    """Parse the scenario payloads' `scenario` block. Cached — the files are static."""
    global _scenario_cache
    if _scenario_cache is not None:
        return _scenario_cache

    out: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(_SCENARIO_DIR, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            sc = payload.get("scenario") or {}
            hub = sc.get("hub") or ""
            if not hub:
                continue
            out.append(
                {
                    "id": _slugify_hub(hub),          # the domain_id
                    "hub": hub,
                    "hub_type": sc.get("hub_type"),
                    # Derived, NOT invented: the payload carries no display title.
                    # 'Strait_of_Hormuz' -> 'Strait of Hormuz'. See the report — a
                    # real title (e.g. a closure/blockade framing) is a CLAIM the
                    # payload does not make, so we do not fabricate one here.
                    "label": hub.replace("_", " "),
                    "aliases": sc.get("aliases") or [],
                    "domain": sc.get("domain") or [],
                    "node_count": len(payload.get("nodes") or []),
                    "edge_count": len(payload.get("edges") or []),
                }
            )
        except Exception as exc:  # noqa: BLE001 — a bad file must not 500 the catalogue
            logger.warning("scenario catalogue: skipping %s (%s)", path, exc)
    _scenario_cache = out
    return out


@router.get("/domains/scenarios")
async def list_scenarios(
    response: Response,
    tier: str = Depends(_get_current_tier),
):
    """Available scenario domains, for the frontend's selector."""
    _require_pro(tier, "Pro subscription required for spatial contagion.")
    for k, v in _NO_STORE_HEADERS.items():
        response.headers[k] = v
    return {"scenarios": _load_scenario_catalogue()}


@router.get("/domains/{domain_id}/spatial-contagion")
async def get_domain_spatial_contagion(
    domain_id: str,
    response: Response,
    db: AsyncSession = Depends(_get_db),
    tier: str = Depends(_get_current_tier),
):
    """
    Spatial contagion graph for ANY domain_id — including the scenario domains
    ('strait_of_hormuz', 'strait_of_malacca') that the literal /domains/global/
    route cannot address.

    ADD-ONLY: the literal 'global' route is declared ABOVE this one and therefore
    still wins for domain_id='global' (FastAPI matches in declaration order), so
    the Omni-Monitor's aggregate behaviour is preserved untouched.

    An unknown/unseeded domain returns 200 with an EMPTY payload, not 404 —
    matching the literal route, which likewise shapes an empty result rather than
    raising. The frontend can then render an honest "no data" state.
    """
    _require_pro(tier, "Pro subscription required for spatial contagion.")
    for k, v in _NO_STORE_HEADERS.items():
        response.headers[k] = v

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
    # _shape_contagion_payload is already null-guarded and emits the new columns.
    return _shape_contagion_payload(domain_id, list(nodes), list(edges))


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
        # NB: `.get("impact_score", 0)` is NOT null-safe — a JSONB key that is
        # PRESENT with a null value returns None, not the default. Filter explicitly,
        # and exclude unmeasured nodes from the max (as everywhere else).
        replay_scores = [
            float(n["impact_score"])
            for n in (newest.nodes_payload or [])
            if isinstance(n, dict) and n.get("impact_score") is not None
        ]
        latest_spatial = {
            "domain_id": domain,
            "nodes": newest.nodes_payload or [],
            "edges": newest.edges_payload or [],
            "epicenter_impact_score": max(replay_scores, default=0.0),
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
