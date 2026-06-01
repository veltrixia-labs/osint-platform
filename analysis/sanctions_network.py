"""
Collateral Damage Network Mapper
================================

PageRank over the Stakeholder / Dependency graph to surface 2nd- and 3rd-order
exposure to sanctioned entities. A node's PageRank centrality is interpreted as
its **collateral-damage risk**: even if not directly sanctioned, a highly-ranked
neighbour of a sanctioned node faces material counterparty exposure.

Algorithm (power iteration; pure-Python, no networkx dependency):

    PR(v) = (1 - d) / N  +  d · Σ_{u ∈ in_neighbors(v)} PR(u) / out_degree(u)

  with d = 0.85, N = total nodes, weighted by Dependency.exposure_weight.

We persist the final PR back to ``Stakeholder.network_score`` so the UI can
render drill-downs without re-running the algorithm per request.

Classification (per node):
  • Primary           — sanctioned_status == True
  • Direct Collateral — 1-hop neighbour of any primary
  • Indirect Collat.  — reachable in ≤2 hops, not in above sets
  • Background        — everything else
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Stakeholder, Dependency

logger = logging.getLogger(__name__)

DEFAULT_DAMPING = 0.85
DEFAULT_MAX_ITERATIONS = 60
DEFAULT_TOLERANCE = 1e-6


def pagerank(
    nodes: List[str],
    edges: List[Tuple[str, str, float]],
    *,
    damping: float = DEFAULT_DAMPING,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tolerance: float = DEFAULT_TOLERANCE,
) -> Dict[str, float]:
    """
    Weighted PageRank in pure Python.

    Args:
        nodes:    list of unique node IDs
        edges:    list of (source_id, target_id, weight) tuples
        damping:  d in the formula
        max_iterations: power-iteration cap
        tolerance: L1-norm convergence threshold

    Returns:
        {node_id: PR-score} normalised so Σ scores == 1
    """
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]: 1.0}

    # Build weighted adjacency: out_total[u] = Σ weights from u
    out_total: Dict[str, float] = {nid: 0.0 for nid in nodes}
    inbound: Dict[str, List[Tuple[str, float]]] = {nid: [] for nid in nodes}
    node_set = set(nodes)
    for src, tgt, w in edges:
        if src not in node_set or tgt not in node_set or w <= 0:
            continue
        out_total[src] += w
        inbound[tgt].append((src, w))

    init = 1.0 / n
    pr: Dict[str, float] = {nid: init for nid in nodes}
    base = (1.0 - damping) / n

    for iteration in range(max_iterations):
        new_pr: Dict[str, float] = {}
        # Dangling-node mass redistributes uniformly.
        dangling_sum = sum(pr[u] for u in nodes if out_total[u] == 0)
        dangling_contrib = damping * dangling_sum / n

        for v in nodes:
            s = 0.0
            for u, w in inbound[v]:
                if out_total[u] > 0:
                    s += pr[u] * (w / out_total[u])
            new_pr[v] = base + dangling_contrib + damping * s

        # Convergence check (L1 distance)
        diff = sum(abs(new_pr[v] - pr[v]) for v in nodes)
        pr = new_pr
        if diff < tolerance:
            logger.debug("PageRank converged after %d iterations (Δ=%.2e)", iteration + 1, diff)
            break

    # Final normalisation (defensive — should already be ≈1 after the loop)
    total = sum(pr.values())
    if total > 0:
        pr = {v: s / total for v, s in pr.items()}
    return pr


async def _load_graph(db: AsyncSession) -> Tuple[List[Stakeholder], List[Dependency]]:
    """Pull the full stakeholders+dependencies graph (intended for batch nightly run)."""
    sh_rows = list((await db.execute(select(Stakeholder))).scalars().all())
    dep_rows = list((await db.execute(select(Dependency))).scalars().all())
    return sh_rows, dep_rows


async def recompute_network_scores(db: AsyncSession) -> Dict[str, Any]:
    """
    Run PageRank over every stakeholder/dependency, write the score back to
    ``Stakeholder.network_score`` for cheap drill-down at runtime.

    Returns a summary suitable for logging / a CLI run.
    """
    stakeholders, dependencies = await _load_graph(db)
    if not stakeholders:
        return {"updated": 0, "node_count": 0, "edge_count": 0, "max_score": 0.0}

    node_ids = [str(s.id) for s in stakeholders]
    edges = [
        (str(d.source_id), str(d.target_id), float(d.exposure_weight or 0.5))
        for d in dependencies
    ]
    scores = pagerank(node_ids, edges)

    by_id = {str(s.id): s for s in stakeholders}
    max_score = max(scores.values()) if scores else 0.0
    updated = 0
    for nid, score in scores.items():
        sh = by_id.get(nid)
        if sh is None:
            continue
        sh.network_score = float(score)
        updated += 1
    await db.commit()

    return {
        "updated": updated,
        "node_count": len(stakeholders),
        "edge_count": len(dependencies),
        "max_score": round(max_score, 6),
    }


def classify_collateral_tier(
    stakeholder: Stakeholder,
    primary_ids: Set[str],
    one_hop_ids: Set[str],
    two_hop_ids: Set[str],
) -> str:
    """Return one of: 'primary', 'direct_collateral', 'indirect_collateral', 'background'."""
    sid = str(stakeholder.id)
    if sid in primary_ids:
        return "primary"
    if sid in one_hop_ids:
        return "direct_collateral"
    if sid in two_hop_ids:
        return "indirect_collateral"
    return "background"


async def expand_collateral_subgraph(
    db: AsyncSession,
    *,
    root_entity_id: Optional[str] = None,
    max_nodes: int = 60,
) -> Dict[str, Any]:
    """
    Build a UI-ready ego-graph for the Collateral Damage Radial Hub.

    If `root_entity_id` is given, the subgraph is the 2-hop neighbourhood of
    that node. Otherwise we surface the top `max_nodes` by network_score that
    are either sanctioned or one-hop neighbours of a sanctioned node.

    Returns:
        {
          "nodes": [{id, name, country, sector, network_score, tier, ...}],
          "edges": [{source_id, target_id, type, weight}],
          "root_entity_id": ...,
          "stats": {...},
        }
    """
    stakeholders, dependencies = await _load_graph(db)
    sh_by_id = {str(s.id): s for s in stakeholders}

    # Outbound / inbound adjacency
    out_adj: Dict[str, List[Dependency]] = {nid: [] for nid in sh_by_id}
    in_adj: Dict[str, List[Dependency]] = {nid: [] for nid in sh_by_id}
    for d in dependencies:
        src = str(d.source_id)
        tgt = str(d.target_id)
        if src in out_adj:
            out_adj[src].append(d)
        if tgt in in_adj:
            in_adj[tgt].append(d)

    primary_ids: Set[str] = {nid for nid, sh in sh_by_id.items() if sh.sanctioned_status}

    if root_entity_id is not None:
        if root_entity_id not in sh_by_id:
            return {"nodes": [], "edges": [], "root_entity_id": root_entity_id,
                    "stats": {"reason": "unknown_root"}}
        seed_ids: Set[str] = {root_entity_id}
    elif primary_ids:
        seed_ids = primary_ids
    else:
        # Fallback: top-N by PageRank when no sanctioned seeds exist yet
        ranked = sorted(sh_by_id.values(), key=lambda s: s.network_score or 0.0, reverse=True)
        seed_ids = {str(s.id) for s in ranked[: min(10, len(ranked))]}

    one_hop_ids: Set[str] = set()
    two_hop_ids: Set[str] = set()
    for sid in seed_ids:
        for d in out_adj.get(sid, []) + in_adj.get(sid, []):
            other = str(d.target_id) if str(d.source_id) == sid else str(d.source_id)
            if other not in seed_ids:
                one_hop_ids.add(other)
    for sid in one_hop_ids:
        for d in out_adj.get(sid, []) + in_adj.get(sid, []):
            other = str(d.target_id) if str(d.source_id) == sid else str(d.source_id)
            if other not in seed_ids and other not in one_hop_ids:
                two_hop_ids.add(other)

    keep_ids = seed_ids | one_hop_ids | two_hop_ids

    # If we still have room and there are highly-ranked unrelated nodes, leave
    # them out (we want a focused collateral graph, not the full universe).
    if len(keep_ids) > max_nodes:
        # Prune two-hop tail first, keeping the highest-score ones
        ranked_two = sorted(two_hop_ids, key=lambda i: sh_by_id[i].network_score or 0.0, reverse=True)
        keep_two = set(ranked_two[: max(0, max_nodes - len(seed_ids) - len(one_hop_ids))])
        keep_ids = seed_ids | one_hop_ids | keep_two
        two_hop_ids = keep_two

    nodes_out: List[Dict[str, Any]] = []
    for nid in keep_ids:
        sh = sh_by_id[nid]
        tier = classify_collateral_tier(sh, primary_ids, one_hop_ids, two_hop_ids)
        nodes_out.append({
            "id": nid,
            "name": sh.name,
            "country": sh.country,
            "sector": sh.sector,
            "domain": sh.domain,
            "ticker": sh.ticker,
            "sanctioned_status": bool(sh.sanctioned_status),
            "sanction_program": sh.sanction_program,
            "pep_score": sh.pep_score,
            "network_score": round(float(sh.network_score or 0.0), 6),
            "tier": tier,
            "accent_color": _tier_color(tier),
        })

    edges_out: List[Dict[str, Any]] = []
    for d in dependencies:
        src = str(d.source_id)
        tgt = str(d.target_id)
        if src in keep_ids and tgt in keep_ids:
            edges_out.append({
                "source_id": src,
                "target_id": tgt,
                "type": d.dependency_type,
                "exposure_weight": float(d.exposure_weight or 0.5),
                "beta_correlation": float(d.beta_correlation or 1.0),
            })

    return {
        "nodes": nodes_out,
        "edges": edges_out,
        "root_entity_id": root_entity_id,
        "stats": {
            "primary_count": sum(1 for n in nodes_out if n["tier"] == "primary"),
            "direct_collateral_count": sum(1 for n in nodes_out if n["tier"] == "direct_collateral"),
            "indirect_collateral_count": sum(1 for n in nodes_out if n["tier"] == "indirect_collateral"),
            "total_nodes": len(nodes_out),
            "total_edges": len(edges_out),
        },
    }


def _tier_color(tier: str) -> str:
    return {
        "primary":              "#dc2626",  # deep red
        "direct_collateral":    "#f59e0b",  # amber
        "indirect_collateral":  "#fbbf24",  # softer amber
        "background":           "#94a3b8",  # slate
    }.get(tier, "#94a3b8")
