"""
Scenario loader — the replacement producer for the spatial graph.

Loads the vault's exported cascade OUTPUT (``data/scenarios/*.json``) into
``spatial_nodes`` / ``spatial_edges`` / ``contagion_history``.

This is a ONE-SHOT loader, deliberately NOT a 5-minute worker. The cascade is
STATIC: it changes only when the vault graph changes and someone re-exports it.
Recomputing it on a timer would be theatre — the old omni_spatial_worker ran
every 5 minutes because its "physics" was a function of the rolling 24h alert
window; a scenario is not.

    python -m jobs.load_scenarios              # load every scenario
    python -m jobs.load_scenarios --dry-run    # print what it WOULD do; touch nothing

What the payloads are: the cascade's *result* — who is affected, by how much,
and why. The 300-node graph, its weights and its sources stay private in the vault.

Cleanup-first per scenario (mirrors the old worker): DELETE that domain's edges,
then its nodes, then INSERT. Other domains are never touched, so this can run
alongside the legacy engine's global/energy/shipping rows.
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import ContagionHistory, SpatialEdge, SpatialNode

logger = logging.getLogger(__name__)

SCENARIO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "scenarios"
)

# The old fake engine's thermodynamic artefacts. A cascade has NO analogue for
# these — there is no rolling alert-entropy or kinematic viscosity in a static
# structural graph. The columns are NOT NULL, so we write 0.0 and say so plainly
# rather than inventing a number.
#
# CONSEQUENCE: analysis/spatial_composite_risk.py reads entropy_index. It is
# hardcoded to the domains 'energy' / 'shipping' / 'supply_chain' and never reads
# scenario domains at all, so a 0.0 here changes nothing today. See the report.
_ENTROPY_INDEX_NOT_APPLICABLE = 0.0
_VISCOSITY_NOT_APPLICABLE = 0.0


def slugify_hub(hub: str) -> str:
    """'Strait_of_Hormuz' -> 'strait_of_hormuz'. This becomes the domain_id."""
    return re.sub(r"[^a-z0-9_]+", "_", hub.strip().lower()).strip("_")


def _as_float(v: Any) -> Optional[float]:
    """None survives as None — an unmeasured magnitude is not zero."""
    return None if v is None else float(v)


def load_payload(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def build_rows(
    payload: Dict[str, Any],
) -> Tuple[str, List[SpatialNode], List[SpatialEdge], List[Dict], List[Dict]]:
    """Map a scenario payload -> ORM rows + JSONB payloads. Pure; no DB access."""
    hub = payload["scenario"]["hub"]
    domain_id = slugify_hub(hub)

    raw_nodes: List[Dict[str, Any]] = payload.get("nodes") or []
    raw_edges: List[Dict[str, Any]] = payload.get("edges") or []

    # A node is a "hybrid" when it IS quantified but has at least one UNQUANTIFIED
    # inbound edge (e.g. Mitsui_OSK: a measured 49 via Japan, plus a direct Malacca
    # exposure that was never quantified). Derive it from the edge set — the edges
    # are the source of truth — and OR in the payload's own flag if it supplied one.
    unq_targets = {
        e.get("target_id")
        for e in raw_edges
        if e.get("unquantified") is True or e.get("intensity") is None
    }

    nodes: List[SpatialNode] = []
    node_payloads: List[Dict[str, Any]] = []
    for n in raw_nodes:
        node_type = n.get("type") or "affected"
        vault_id = n.get("id")
        hybrid = bool(n.get("has_unquantified_direct_edge")) or (
            node_type != "exposed_unquantified" and vault_id in unq_targets
        )
        row = SpatialNode(
            id=uuid.uuid4(),
            domain_id=domain_id,
            name=n.get("name") or vault_id or "Unknown",
            lat=float(n["lat"]),
            lon=float(n["lon"]),
            impact_score=_as_float(n.get("impact_score")),   # may be NULL — the point
            node_type=node_type,
            is_epicenter=(node_type == "epicenter"),         # keep the legacy flag in sync
            node_id=vault_id,
            country=n.get("country"),
            order_level=n.get("order"),
            confidence=_as_float(n.get("confidence")),
            why=n.get("why"),
            has_unquantified_direct_edge=hybrid,
            entropy_index=_ENTROPY_INDEX_NOT_APPLICABLE,     # see module docstring
        )
        nodes.append(row)
        node_payloads.append(
            {
                "id": vault_id or str(row.id),
                "domain_id": domain_id,
                "name": row.name,
                "lat": row.lat,
                "lon": row.lon,
                "impact_score": row.impact_score,
                "entropy_index": row.entropy_index,
                "type": node_type,
                "country": row.country,
                "order": row.order_level,
                "confidence": row.confidence,
                "why": row.why,
                "has_unquantified_direct_edge": hybrid,
            }
        )

    edges: List[SpatialEdge] = []
    edge_payloads: List[Dict[str, Any]] = []
    for e in raw_edges:
        intensity = _as_float(e.get("intensity"))
        unquantified = bool(e.get("unquantified")) or intensity is None
        row = SpatialEdge(
            id=uuid.uuid4(),
            domain_id=domain_id,
            source_lat=float(e["source_lat"]),
            source_lon=float(e["source_lon"]),
            target_lat=float(e["target_lat"]),
            target_lon=float(e["target_lon"]),
            edge_intensity=intensity,                        # may be NULL — the point
            unquantified=unquantified,
            source_node_id=e.get("source_id"),
            target_node_id=e.get("target_id"),
            order_level=int(e.get("target_order") or 2),
            viscosity_coefficient=_VISCOSITY_NOT_APPLICABLE,
        )
        edges.append(row)
        edge_payloads.append(
            {
                "source_lat": row.source_lat,
                "source_lon": row.source_lon,
                "target_lat": row.target_lat,
                "target_lon": row.target_lon,
                "intensity": intensity,
                "edge_intensity": intensity,
                "unquantified": unquantified,
                "source_id": row.source_node_id,
                "target_id": row.target_node_id,
                "order_level": row.order_level,
                "target_order": row.order_level,
                "viscosity_coefficient": row.viscosity_coefficient,
            }
        )

    return domain_id, nodes, edges, node_payloads, edge_payloads


async def load_scenario(
    session: Optional[AsyncSession], path: str, *, dry_run: bool
) -> Dict[str, Any]:
    """`session` may be None ONLY for a dry run — a preview of what WOULD be
    inserted must not require a live database."""
    payload = load_payload(path)
    domain_id, nodes, edges, node_payloads, edge_payloads = build_rows(payload)

    null_scores = sum(1 for n in nodes if n.impact_score is None)
    null_intens = sum(1 for e in edges if e.edge_intensity is None)
    hybrids = [n.node_id for n in nodes if n.has_unquantified_direct_edge]

    from sqlalchemy import func, select

    if session is None:
        if not dry_run:
            raise RuntimeError("a real load requires a database session")
        existing_nodes = existing_edges = None   # unknown without a DB
    else:
        existing_nodes = (
            await session.execute(
                select(func.count(SpatialNode.id)).where(SpatialNode.domain_id == domain_id)
            )
        ).scalar() or 0
        existing_edges = (
            await session.execute(
                select(func.count(SpatialEdge.id)).where(SpatialEdge.domain_id == domain_id)
            )
        ).scalar() or 0

    summary = {
        "scenario": os.path.basename(path),
        "domain_id": domain_id,
        "delete_nodes": existing_nodes,
        "delete_edges": existing_edges,
        "insert_nodes": len(nodes),
        "insert_edges": len(edges),
        "null_impact_score": null_scores,
        "null_edge_intensity": null_intens,
        "hybrid_nodes": hybrids,
    }

    if dry_run:
        return summary

    # Cleanup-first: edges before nodes; only THIS domain.
    await session.execute(delete(SpatialEdge).where(SpatialEdge.domain_id == domain_id))
    await session.execute(delete(SpatialNode).where(SpatialNode.domain_id == domain_id))
    for n in nodes:
        session.add(n)
    for e in edges:
        session.add(e)

    # One snapshot so the Time Machine has something to read. The cascade is static,
    # so history never grows — the TM will show a single frame (slider pinned, no
    # trajectory). That is honest: there IS no time dimension to a static cascade.
    session.add(
        ContagionHistory(
            id=uuid.uuid4(),
            domain_id=domain_id,
            snapshot_timestamp=datetime.now(timezone.utc),
            nodes_payload=node_payloads,
            edges_payload=edge_payloads,
            entropy_index=_ENTROPY_INDEX_NOT_APPLICABLE,
            viscosity_coefficient=_VISCOSITY_NOT_APPLICABLE,
            phase_transition_warning=False,
        )
    )
    return summary


async def run(dry_run: bool = False) -> List[Dict[str, Any]]:
    paths = sorted(glob.glob(os.path.join(SCENARIO_DIR, "*.json")))
    if not paths:
        logger.warning("No scenarios found in %s", SCENARIO_DIR)
        return []

    summaries: List[Dict[str, Any]] = []

    if dry_run:
        # A dry run must work with no DB configured (e.g. a laptop without prod
        # secrets). If we can't connect, we still preview every INSERT — only the
        # DELETE counts are unknowable.
        session: Optional[AsyncSession] = None
        try:
            async with AsyncSessionLocal() as s:
                for p in paths:
                    summaries.append(await load_scenario(s, p, dry_run=True))
                await s.rollback()
            return summaries
        except Exception as exc:  # noqa: BLE001 — any DB/driver failure is fine here
            logger.warning("dry-run: no database (%s) — DELETE counts unknown", exc)
            summaries = []
            for p in paths:
                summaries.append(await load_scenario(None, p, dry_run=True))
            return summaries

    async with AsyncSessionLocal() as session:
        for p in paths:
            summaries.append(await load_scenario(session, p, dry_run=False))
        await session.commit()
    return summaries


def _print(summaries: List[Dict[str, Any]], dry_run: bool) -> None:
    banner = "DRY RUN — nothing written" if dry_run else "LOADED"
    print(f"\n=== scenario loader: {banner} ===")
    for s in summaries:
        dn = s["delete_nodes"]
        de = s["delete_edges"]
        dn_s = "unknown (no DB)" if dn is None else dn
        de_s = "unknown (no DB)" if de is None else de
        print(f"\n{s['scenario']}  ->  domain_id='{s['domain_id']}'")
        print(f"   DELETE  nodes={dn_s}  edges={de_s}")
        print(f"   INSERT  nodes={s['insert_nodes']}  edges={s['insert_edges']}")
        print(
            f"   NULL    impact_score={s['null_impact_score']}  "
            f"edge_intensity={s['null_edge_intensity']}"
            "   <- the first nulls this DB will ever hold"
        )
        if s["hybrid_nodes"]:
            print(
                f"   HYBRID  quantified nodes with an unquantified direct edge: "
                f"{', '.join(str(x) for x in s['hybrid_nodes'])}"
            )
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Load vault scenario cascades into the spatial tables.")
    ap.add_argument("--dry-run", action="store_true", help="print what would be written; touch nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    summaries = asyncio.run(run(dry_run=args.dry_run))
    _print(summaries, args.dry_run)


if __name__ == "__main__":
    main()
