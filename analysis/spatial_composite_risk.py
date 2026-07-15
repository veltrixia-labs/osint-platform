"""
Pro-domain → Spatial Engine domain-id aliasing.

Formerly also housed `compute_composite_multiplier`, a cross-domain "composite
risk" scalar derived from the fake spatial engine's entropy_index. That metric
was removed: its trigger threshold was never crossed by real data and one of its
two sink domains (`supply_chain`) never existed, so it only ever asserted
"Stable" — a confident verdict from a dead signal. Only the domain-alias helper,
which is a live dependency of pro_structural_context, remains.
"""
from __future__ import annotations

from typing import Dict

# Aliases from the long topic_code form (used by Pro reports) to the short
# Spatial Engine domain_id form (used by spatial_nodes/edges). Kept in sync
# with the frontend's SPATIAL_DOMAIN_ALIAS table.
_TOPIC_TO_SPATIAL: Dict[str, str] = {
    "energy_resource_risk": "energy",
    "supply_chain_intelligence": "shipping",
    # supply_chain is also seeded directly under its plain id.
}


def topic_to_spatial_domain(topic_code: str) -> str:
    """
    Map a Pro Report's long topic_code to the corresponding short spatial
    domain_id. Identity if no alias is known.
    """
    return _TOPIC_TO_SPATIAL.get(topic_code, topic_code)
