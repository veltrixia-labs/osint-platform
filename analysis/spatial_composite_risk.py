"""
Phase 7.4 — Cross-domain composite-risk synthesis.

A lightweight module that reads the dedicated Spatial Engine tables
(`spatial_nodes`, `spatial_edges`) and computes a single scalar
**composite multiplier** describing how much the live system is amplifying
risk across domains. Returned alongside the primary propagation path
("Energy → Supply Chain") so the Pro Brief can render it directly.

This intentionally replaces the static `_DEFAULT_CROSS_DOMAIN_SPILLOVER`
table in `pro_structural_compiler.py` whenever live spatial data exists.
Falls back to a multiplier of 1.0 (no amplification) when the spatial
tables are unseeded.

Public surface:
    compute_composite_multiplier(db_session, current_context) -> dict
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SpatialNode

logger = logging.getLogger(__name__)

# The frontend Critical Alert pulse fires at impact_score >= 75 (1.5x of a
# 50-point baseline). We use the same 1.5x ratio for entropy: the trigger
# is entropy_index >= 0.75 against a 0.5 calm-state baseline.
_ENTROPY_HIGH_THRESHOLD = 0.75
_ENTROPY_ACTIVE_THRESHOLD = 0.30

# Composite multiplier band — 1.0 = no amplification, 2.5 = max spillover
# we'll surface to the UI.
_MULTIPLIER_FLOOR = 1.0
_MULTIPLIER_CEILING = 2.5

# Aliases from the long topic_code form (used by Pro reports) to the short
# Spatial Engine domain_id form (used by spatial_nodes/edges). Kept in sync
# with the frontend's SPATIAL_DOMAIN_ALIAS table.
_TOPIC_TO_SPATIAL: Dict[str, str] = {
    "energy_resource_risk": "energy",
    "supply_chain_intelligence": "shipping",
    # supply_chain is also seeded directly under its plain id.
}

# Domains that participate in the composite calc (short ids).
_TRIGGER_DOMAINS = ("energy", "shipping")
_SINK_DOMAINS    = ("shipping", "supply_chain")


async def _mean_entropy_for(
    db: AsyncSession, domain_id: str,
) -> float:
    """Average entropy_index over a domain's live spatial nodes. 0 if empty."""
    rows = (
        await db.execute(
            select(SpatialNode.entropy_index)
            .where(SpatialNode.domain_id == domain_id)
        )
    ).scalars().all()
    if not rows:
        return 0.0
    cleaned = [float(v) for v in rows if v is not None]
    if not cleaned:
        return 0.0
    return sum(cleaned) / len(cleaned)


def _format_path(triggered: List[str], sinks: List[str]) -> str:
    """Build the human-readable arrow path. Title-cases each segment."""
    parts: List[str] = []
    for d in triggered:
        parts.append(d.replace("_", " ").title())
    for d in sinks:
        # Avoid printing the same node twice if a trigger also acts as a sink.
        label = d.replace("_", " ").title()
        if label not in parts:
            parts.append(label)
    return " → ".join(parts) if parts else "Stable (no cross-domain spillover)"


async def compute_composite_multiplier(
    db_session: AsyncSession,
    current_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Read the live spatial graph and synthesise a cross-domain
    amplification score.

    Returns a dict shaped:
        {
          "composite_multiplier": 1.0..2.5,
          "primary_propagation_path": "Energy → Supply Chain",
          "trigger_domains": ["energy"],
          "supporting_signals": {
              "energy_entropy": 0.83,
              "shipping_entropy": 0.41,
              "supply_chain_entropy": 0.55,
          },
          "schema_version": "composite_risk_v1",
        }

    `current_context` is reserved for future weighting (e.g. boost the
    multiplier if the active brief is rooted in the trigger domain).
    Currently unused but kept on the signature for forward-compat.
    """
    del current_context  # reserved — see docstring

    # Pull entropy for every domain we care about in one async pass.
    energy_entropy       = await _mean_entropy_for(db_session, "energy")
    shipping_entropy     = await _mean_entropy_for(db_session, "shipping")
    supply_chain_entropy = await _mean_entropy_for(db_session, "supply_chain")

    triggered: List[str] = []
    if energy_entropy   >= _ENTROPY_HIGH_THRESHOLD: triggered.append("energy")
    if shipping_entropy >= _ENTROPY_HIGH_THRESHOLD: triggered.append("shipping")

    # A "sink" is any downstream domain that's currently active — even if
    # its own entropy is below the high threshold, it can still absorb
    # spillover. The propagation path is only meaningful when there's at
    # least one trigger AND one sink.
    sinks: List[str] = []
    if shipping_entropy     >= _ENTROPY_ACTIVE_THRESHOLD: sinks.append("shipping")
    if supply_chain_entropy >= _ENTROPY_ACTIVE_THRESHOLD: sinks.append("supply_chain")

    if not triggered or not sinks:
        return {
            "composite_multiplier": _MULTIPLIER_FLOOR,
            "primary_propagation_path": "Stable (no cross-domain spillover)",
            "trigger_domains": triggered,
            "supporting_signals": {
                "energy_entropy": round(energy_entropy, 3),
                "shipping_entropy": round(shipping_entropy, 3),
                "supply_chain_entropy": round(supply_chain_entropy, 3),
            },
            "schema_version": "composite_risk_v1",
        }

    # Amplification model — convex combination of trigger entropy and the
    # strongest active sink. Floor 1.0, ceiling 2.5.
    trigger_strength = max(
        energy_entropy   if "energy"   in triggered else 0.0,
        shipping_entropy if "shipping" in triggered else 0.0,
    )
    sink_strength = max(
        shipping_entropy     if "shipping"     in sinks else 0.0,
        supply_chain_entropy if "supply_chain" in sinks else 0.0,
    )
    # When trigger=1.0 and sink=1.0, multiplier reaches 2.5.
    multiplier = _MULTIPLIER_FLOOR + 1.5 * trigger_strength * sink_strength
    multiplier = max(_MULTIPLIER_FLOOR, min(_MULTIPLIER_CEILING, multiplier))

    return {
        "composite_multiplier": round(multiplier, 3),
        "primary_propagation_path": _format_path(triggered, sinks),
        "trigger_domains": triggered,
        "supporting_signals": {
            "energy_entropy": round(energy_entropy, 3),
            "shipping_entropy": round(shipping_entropy, 3),
            "supply_chain_entropy": round(supply_chain_entropy, 3),
        },
        "schema_version": "composite_risk_v1",
    }


def topic_to_spatial_domain(topic_code: str) -> str:
    """
    Map a Pro Report's long topic_code to the corresponding short spatial
    domain_id. Identity if no alias is known.
    """
    return _TOPIC_TO_SPATIAL.get(topic_code, topic_code)
