"""
Phase 7.1 — Seed the dedicated Spatial Engine tables.

Wipes (`delete()`) and repopulates:
  • spatial_nodes        — one per geo entity, per domain
  • spatial_edges        — N-th order ripples
  • contagion_history    — 5 snapshots spread over the last 24h

Domains seeded:
  • global    — aggregate / Omni-Monitor canonical view
  • energy    — Middle East energy corridor & dependants
  • shipping  — chokepoint network (Hormuz / Suez / Malacca / Panama)

Run it directly:

    python scratch/seed_spatial_data.py
"""
from __future__ import annotations

import asyncio
import math
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import delete

from db.database import AsyncSessionLocal
from db.models import SpatialNode, SpatialEdge, ContagionHistory


# ── Geo registry ──────────────────────────────────────────────────────────
#
# (key, name, lat, lon, base_impact, is_epicenter)
GEO: Dict[str, Tuple[str, float, float, float, bool]] = {
    "me_energy":     ("Middle East Energy Corridor", 26.6,  56.2, 96.0, True),
    "red_sea":       ("Red Sea / Bab el-Mandeb",     12.6,  43.3, 84.0, False),
    "suez":          ("Suez Canal",                  30.5,  32.3, 81.0, False),
    "mediterranean": ("Eastern Mediterranean",       34.0,  28.0, 72.0, False),
    "europe":        ("Eastern Europe Frontier",     49.0,  31.3, 78.0, False),
    "north_sea":     ("North Sea Energy Hub",        57.0,   3.0, 68.0, False),
    "south_china":   ("South China Sea",             13.5, 114.5, 88.0, False),
    "taiwan":        ("Taiwan Strait",               24.1, 121.0, 79.0, False),
    "malacca":       ("Malacca Strait",               2.5, 101.4, 86.0, False),
    "panama":        ("Panama Canal",                 9.1, -79.7, 71.0, False),
}


def _node(domain_id: str, key: str, impact_override: float | None = None,
          entropy: float = 0.6) -> SpatialNode:
    name, lat, lon, base_impact, is_epi = GEO[key]
    return SpatialNode(
        id=uuid.uuid4(),
        domain_id=domain_id,
        name=name,
        lat=lat,
        lon=lon,
        impact_score=impact_override if impact_override is not None else base_impact,
        entropy_index=entropy,
        is_epicenter=is_epi,
    )


def _edge(domain_id: str, src_key: str, tgt_key: str,
          order_level: int, intensity: float,
          viscosity: float = 0.08) -> SpatialEdge:
    _, src_lat, src_lon, *_ = GEO[src_key]
    _, tgt_lat, tgt_lon, *_ = GEO[tgt_key]
    return SpatialEdge(
        id=uuid.uuid4(),
        domain_id=domain_id,
        source_lat=src_lat,
        source_lon=src_lon,
        target_lat=tgt_lat,
        target_lon=tgt_lon,
        edge_intensity=intensity,
        viscosity_coefficient=viscosity,
        order_level=order_level,
    )


# ── Per-domain graph specifications ───────────────────────────────────────

def _graph_global() -> Tuple[List[SpatialNode], List[SpatialEdge]]:
    nodes = [
        _node("global", "me_energy",   entropy=0.88),
        _node("global", "red_sea",     entropy=0.74),
        _node("global", "europe",      entropy=0.66),
        _node("global", "south_china", entropy=0.72),
        _node("global", "taiwan",      entropy=0.61),
        _node("global", "malacca",     entropy=0.69),
    ]
    edges = [
        # Order 1 — direct epicenter outflow
        _edge("global", "me_energy", "red_sea",     1, 0.92, 0.11),
        _edge("global", "me_energy", "europe",      1, 0.85, 0.10),
        _edge("global", "me_energy", "south_china", 1, 0.81, 0.10),
        # Order 2 — first hop downstream
        _edge("global", "red_sea",     "malacca", 2, 0.71, 0.07),
        _edge("global", "south_china", "taiwan",  2, 0.66, 0.07),
        # Order 3 — second hop fringe
        _edge("global", "malacca", "taiwan",  3, 0.42, 0.05),
    ]
    return nodes, edges


def _graph_energy() -> Tuple[List[SpatialNode], List[SpatialEdge]]:
    nodes = [
        _node("energy", "me_energy",     entropy=0.91),
        _node("energy", "red_sea",       entropy=0.78),
        _node("energy", "suez",          entropy=0.72),
        _node("energy", "north_sea",     entropy=0.58),
        _node("energy", "mediterranean", entropy=0.62),
    ]
    edges = [
        _edge("energy", "me_energy", "red_sea",       1, 0.94, 0.12),
        _edge("energy", "me_energy", "mediterranean", 1, 0.83, 0.10),
        _edge("energy", "red_sea",   "suez",          2, 0.76, 0.08),
        _edge("energy", "suez",      "north_sea",     3, 0.48, 0.05),
    ]
    return nodes, edges


def _graph_shipping() -> Tuple[List[SpatialNode], List[SpatialEdge]]:
    nodes = [
        _node("shipping", "me_energy",   impact_override=92.0, entropy=0.86),
        _node("shipping", "malacca",     entropy=0.81),
        _node("shipping", "suez",        entropy=0.74),
        _node("shipping", "panama",      entropy=0.55),
        _node("shipping", "south_china", entropy=0.77),
        _node("shipping", "taiwan",      entropy=0.63),
    ]
    edges = [
        _edge("shipping", "me_energy", "malacca",     1, 0.89, 0.11),
        _edge("shipping", "me_energy", "suez",        1, 0.84, 0.10),
        _edge("shipping", "malacca",   "south_china", 2, 0.72, 0.08),
        _edge("shipping", "south_china","taiwan",     2, 0.65, 0.07),
        _edge("shipping", "suez",      "panama",      3, 0.38, 0.05),
    ]
    return nodes, edges


# ── Historical snapshots ──────────────────────────────────────────────────

def _historical_snapshot(
    domain_id: str,
    nodes: List[SpatialNode],
    edges: List[SpatialEdge],
    ts: datetime,
    entropy: float,
    viscosity: float,
) -> ContagionHistory:
    """One row of ContagionHistory backed by JSONB serialisations."""
    return ContagionHistory(
        id=uuid.uuid4(),
        domain_id=domain_id,
        snapshot_timestamp=ts,
        nodes_payload=[
            {
                "id": str(n.id),
                "name": n.name,
                "lat": n.lat,
                "lon": n.lon,
                "impact_score": n.impact_score,
                "entropy_index": n.entropy_index,
                "type": "epicenter" if n.is_epicenter else "affected",
            } for n in nodes
        ],
        edges_payload=[
            {
                "source_lat": e.source_lat, "source_lon": e.source_lon,
                "target_lat": e.target_lat, "target_lon": e.target_lon,
                "intensity": e.edge_intensity,
                "order_level": e.order_level,
                "target_order": e.order_level,
            } for e in edges
        ],
        entropy_index=entropy,
        viscosity_coefficient=viscosity,
        # Trigger the frontend's phase-transition chip on snapshots that
        # cross both thresholds (matches systemic-fragility logic).
        phase_transition_warning=(entropy >= 0.85 and viscosity >= 0.10),
    )


def _build_history_for_domain(
    domain_id: str,
    nodes: List[SpatialNode],
    edges: List[SpatialEdge],
    now: datetime,
) -> List[ContagionHistory]:
    """Five snapshots evenly spaced over the last 24 hours. Entropy/viscosity
    trace a rising-then-cooling curve so the frontend's slider scrubs
    through visibly different states."""
    out: List[ContagionHistory] = []
    n_snaps = 5
    for i in range(n_snaps):
        # 0..1 along the 24h window — t=1 is "now".
        t = i / (n_snaps - 1)
        ts = now - timedelta(hours=24 * (1 - t))
        # Rising-cooling entropy curve, peak at the middle snapshot.
        peak_offset = abs(t - 0.5) * 2     # 0 at peak, 1 at extremes
        entropy = 0.92 - 0.30 * peak_offset
        viscosity = 0.14 - 0.06 * peak_offset
        out.append(_historical_snapshot(
            domain_id, nodes, edges, ts, entropy, viscosity,
        ))
    return out


# ── Main ──────────────────────────────────────────────────────────────────

async def seed() -> int:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        # Cleanup-First: drop every existing row in the three tables so
        # repeated runs are idempotent. No defensive "INSERT OR UPDATE".
        await db.execute(delete(ContagionHistory))
        await db.execute(delete(SpatialEdge))
        await db.execute(delete(SpatialNode))
        await db.commit()
        print("[seed] cleared spatial_nodes / spatial_edges / contagion_history")

        per_domain: List[Tuple[str, List[SpatialNode], List[SpatialEdge]]] = [
            ("global",   *_graph_global()),
            ("energy",   *_graph_energy()),
            ("shipping", *_graph_shipping()),
        ]

        total_nodes = 0
        total_edges = 0
        for domain_id, nodes, edges in per_domain:
            for n in nodes: db.add(n)
            for e in edges: db.add(e)
            total_nodes += len(nodes)
            total_edges += len(edges)
            for snap in _build_history_for_domain(domain_id, nodes, edges, now):
                db.add(snap)
            print(f"[seed] {domain_id:<10s} nodes={len(nodes)} edges={len(edges)} snapshots=5")

        await db.commit()
        print(f"[seed] committed {total_nodes} nodes, {total_edges} edges, "
              f"{len(per_domain) * 5} history snapshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(seed()))
