"""
Maritime Choke-Point Catalog.

Six fixed nodes that dominate global crude/LNG/container flow. Each pairs with:
  - An EIA series (or proxy macro series) that quantifies *physical* flow.
  - A list of strategic topics whose alerts represent *OSINT viscosity*.
  - lat/lng for the choke-point map.

The Fluid Dynamics engine combines `physical_flow` with `osint_viscosity`
to compute a downstream sector restriction factor.

Sources:
  - EIA short-term energy outlook (oil transit)
  - WSC trade lane statistics (Strait of Malacca, Suez)
  - Daily news flows are tracked via existing AlertLog rows on the topics below.

No external runtime fetch is required for the choke-point geometry — these
positions and downstream maps are stable on multi-decade timescales.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Each maritime choke-point we model. ``daily_volume_mbpd`` is the IEA / EIA
# nominal daily crude / equivalent throughput in millions of barrels per day
# (or container-equivalent for non-energy chokes). Values are static baseline
# magnitudes — actual real-time flow is read from EIA when available.
CHOKE_POINTS: List[Dict[str, Any]] = [
    {
        "id": "strait_of_hormuz",
        "label": "Strait of Hormuz",
        "lat": 26.5667,
        "lng": 56.2500,
        "daily_volume_mbpd": 21.0,   # ~21% of global petroleum liquids
        "primary_commodity": "crude_oil",
        "eia_series": ["WTTSTUS1", "WCESTUS1"],
        "osint_topics": ["energy_resource_risk", "defense_technology"],
        "downstream_sectors": ["energy_resource_risk", "supply_chain_intelligence", "global_market_intelligence"],
        "description": "Carries ~21 mbpd of seaborne oil — single most strategically sensitive chokepoint."
    },
    {
        "id": "strait_of_malacca",
        "label": "Strait of Malacca",
        "lat": 2.5000,
        "lng": 102.0000,
        "daily_volume_mbpd": 16.0,
        "primary_commodity": "crude_oil",
        "eia_series": [],
        "osint_topics": ["supply_chain_intelligence", "ai_semiconductor_intelligence", "defense_technology"],
        "downstream_sectors": ["ai_semiconductor_intelligence", "supply_chain_intelligence", "global_market_intelligence"],
        "description": "Primary East Asian oil + container artery linking the Indian Ocean to the Pacific."
    },
    {
        "id": "suez_canal",
        "label": "Suez Canal",
        "lat": 30.5852,
        "lng": 32.2654,
        "daily_volume_mbpd": 9.2,
        "primary_commodity": "container_oil_mix",
        "eia_series": [],
        "osint_topics": ["supply_chain_intelligence", "energy_resource_risk", "defense_technology"],
        "downstream_sectors": ["supply_chain_intelligence", "energy_resource_risk", "global_market_intelligence"],
        "description": "Connects Med to Red Sea; carries ~12% of global container TEU."
    },
    {
        "id": "bab_el_mandeb",
        "label": "Bab el-Mandeb",
        "lat": 12.5833,
        "lng": 43.3333,
        "daily_volume_mbpd": 6.2,
        "primary_commodity": "crude_oil",
        "eia_series": [],
        "osint_topics": ["energy_resource_risk", "defense_technology", "supply_chain_intelligence"],
        "downstream_sectors": ["supply_chain_intelligence", "energy_resource_risk"],
        "description": "Gateway to Suez from the Indian Ocean — Houthi attack vector since 2023."
    },
    {
        "id": "panama_canal",
        "label": "Panama Canal",
        "lat": 9.0820,
        "lng": -79.6800,
        "daily_volume_mbpd": 0.8,
        "primary_commodity": "container_lng",
        "eia_series": [],
        "osint_topics": ["supply_chain_intelligence", "energy_resource_risk"],
        "downstream_sectors": ["supply_chain_intelligence", "global_market_intelligence"],
        "description": "US Gulf↔Pacific link; drought-induced draft restrictions cause cyclical bottlenecks."
    },
    {
        "id": "bosphorus_strait",
        "label": "Bosphorus Strait",
        "lat": 41.1191,
        "lng": 29.0700,
        "daily_volume_mbpd": 2.9,
        "primary_commodity": "crude_oil",
        "eia_series": [],
        "osint_topics": ["energy_resource_risk", "defense_technology"],
        "downstream_sectors": ["energy_resource_risk", "global_market_intelligence"],
        "description": "Russian/Caspian oil export route through Turkish waters."
    },
]


def get_choke_points() -> List[Dict[str, Any]]:
    """Return all configured choke-points (the engine consumes this directly)."""
    return list(CHOKE_POINTS)


def get_choke_point(node_id: str) -> Dict[str, Any] | None:
    for cp in CHOKE_POINTS:
        if cp["id"] == node_id:
            return cp
    return None
