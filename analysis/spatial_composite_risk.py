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

# Aliases from the long topic_code form (used by Pro reports) to the real
# scenario domain_id (a loaded cascade in spatial_nodes/edges).
#
# Only the two topics a real scenario legitimately serves are mapped. All four
# vault scenarios (strait_of_hormuz, strait_of_malacca, bab_el-mandeb,
# suez_canal) tag [supply_chain, energy]; NONE tags ai_semiconductor, crypto,
# defense, or global_market — so those four topics intentionally have no spatial
# domain and render no spatial section (see _fetch_live_spatial_graph, which now
# returns None rather than an empty/relic placeholder). Fixed mapping for now;
# dynamic selection of the currently-firing scenario is a separate task.
_TOPIC_TO_SPATIAL: Dict[str, str] = {
    "energy_resource_risk": "strait_of_hormuz",
    "supply_chain_intelligence": "strait_of_malacca",
}


def topic_to_spatial_domain(topic_code: str) -> str:
    """
    Map a Pro Report's long topic_code to the corresponding short spatial
    domain_id. Identity if no alias is known.
    """
    return _TOPIC_TO_SPATIAL.get(topic_code, topic_code)
