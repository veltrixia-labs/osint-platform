"""
Omni-Domain Spatial Physics Engine (Phase 7.2).

Translates clustered RSS / AlertLog signals into spatial contagion graphs using
internal mathematical models only (Shannon entropy, kinematic viscosity, network
decay). No LLM or external geocoding APIs — coordinates come from AlertLog fields
or the offline ``GeoLocator`` (``data/geo_master.db``).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from analysis.intensity_pressure import raw_intensity_from_alert, ui_display_intensity
from analysis.pro_structural_context import _GEO_KEYWORDS, _ISO_TO_MAJOR_CITY
from analysis.pro_systemic_physics import SystemicFragilityEngine

logger = logging.getLogger(__name__)

# Frontend critical pulse threshold (SpatialNode.impact_score).
CRITICAL_IMPACT_THRESHOLD = 75.0
# Entropy spike vs rolling historical mean → phase transition warning.
ENTROPY_SPIKE_RATIO = 1.5
# Default geographic snap radius (km) when assigning alerts to registry sites.
MAX_SITE_ASSIGN_KM = 1400.0
# Bounding box radius for density / cluster-size proxy (degrees ≈ 550 km at equator).
SITE_BOX_DEG = 5.0

OMNI_SPATIAL_DOMAINS: Tuple[str, ...] = ("global", "energy", "shipping")

# Map strategic Pro domain IDs → Omni spatial table domain_id values.
PRO_DOMAIN_TO_OMNI: Dict[str, str] = {
    "energy_resource_risk": "energy",
    "supply_chain_intelligence": "shipping",
    "global_market_intelligence": "global",
    "ai_semiconductor_intelligence": "global",
    "defense_technology": "global",
    "crypto_geopolitics": "global",
}

# Registry site_key → (display name, lat, lon, base_weight for epicenter ranking)
GEO_REGISTRY: Dict[str, Tuple[str, float, float, float]] = {
    "me_energy": ("Middle East Energy Corridor", 26.6, 56.2, 1.0),
    "red_sea": ("Red Sea / Bab el-Mandeb", 12.6, 43.3, 0.85),
    "suez": ("Suez Canal", 30.5, 32.3, 0.80),
    "mediterranean": ("Eastern Mediterranean", 34.0, 28.0, 0.72),
    "europe": ("Eastern Europe Frontier", 49.0, 31.3, 0.78),
    "north_sea": ("North Sea Energy Hub", 57.0, 3.0, 0.68),
    "south_china": ("South China Sea", 13.5, 114.5, 0.88),
    "taiwan": ("Taiwan Strait", 24.1, 121.0, 0.79),
    "malacca": ("Malacca Strait", 2.5, 101.4, 0.86),
    "panama": ("Panama Canal", 9.1, -79.7, 0.71),
}

# Per-domain directed edges: (source_key, target_key, order_level, base_intensity)
DOMAIN_EDGE_TOPOLOGY: Dict[str, List[Tuple[str, str, int, float]]] = {
    "global": [
        ("me_energy", "red_sea", 1, 0.92),
        ("me_energy", "europe", 1, 0.85),
        ("me_energy", "south_china", 1, 0.81),
        ("red_sea", "malacca", 2, 0.71),
        ("south_china", "taiwan", 2, 0.66),
        ("malacca", "taiwan", 3, 0.42),
    ],
    "energy": [
        ("me_energy", "red_sea", 1, 0.94),
        ("me_energy", "mediterranean", 1, 0.83),
        ("red_sea", "suez", 2, 0.76),
        ("suez", "north_sea", 3, 0.48),
    ],
    "shipping": [
        ("me_energy", "malacca", 1, 0.89),
        ("me_energy", "suez", 1, 0.84),
        ("malacca", "south_china", 2, 0.72),
        ("south_china", "taiwan", 2, 0.65),
        ("suez", "panama", 3, 0.38),
    ],
}

# Sites considered per omni domain (subset of registry).
DOMAIN_SITE_KEYS: Dict[str, Tuple[str, ...]] = {
    "global": ("me_energy", "red_sea", "europe", "south_china", "taiwan", "malacca"),
    "energy": ("me_energy", "red_sea", "suez", "mediterranean", "north_sea"),
    "shipping": ("me_energy", "malacca", "suez", "panama", "south_china", "taiwan"),
}


@dataclass
class AlertGeoEvent:
    """One alert normalised for spatial physics."""
    alert_id: str
    domain_id: str
    lat: float
    lon: float
    raw_intensity: float
    ui_intensity: float
    triggered_at: datetime
    site_key: Optional[str] = None
    label: str = ""


@dataclass
class ComputedSpatialNode:
    site_key: str
    name: str
    lat: float
    lon: float
    impact_score: float
    entropy_index: float
    viscosity_coefficient: float
    is_epicenter: bool
    phase_transition_warning: bool
    event_count: int = 0
    cluster_density: float = 0.0


@dataclass
class ComputedSpatialEdge:
    source_lat: float
    source_lon: float
    target_lat: float
    target_lon: float
    edge_intensity: float
    viscosity_coefficient: float
    order_level: int


@dataclass
class DomainSpatialGraph:
    domain_id: str
    nodes: List[ComputedSpatialNode] = field(default_factory=list)
    edges: List[ComputedSpatialEdge] = field(default_factory=list)
    phase_transition_warning: bool = False
    mean_entropy: float = 0.0
    mean_viscosity: float = 0.0


def omni_domain_for_pro_domain(pro_domain_id: str) -> str:
    return PRO_DOMAIN_TO_OMNI.get(pro_domain_id, "global")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def _in_bbox(lat: float, lon: float, center_lat: float, center_lon: float, deg: float) -> bool:
    return abs(lat - center_lat) <= deg and abs(lon - center_lon) <= deg


def _keyword_hits(text: str) -> List[str]:
    if not text:
        return []
    hits: List[str] = []
    lower = text.casefold()
    for kw in _GEO_KEYWORDS:
        if kw.casefold() in lower:
            hits.append(kw)
    return hits


class SpatialPhysicsEngine:
    """
    Stateless physics calculator. Pass pre-fetched alerts; receive graph payloads
    ready for ``SpatialNode`` / ``SpatialEdge`` persistence.
    """

    def __init__(
        self,
        *,
        window_hours: float = 24.0,
        entropy_spike_ratio: float = ENTROPY_SPIKE_RATIO,
        critical_impact: float = CRITICAL_IMPACT_THRESHOLD,
    ) -> None:
        self.window_hours = float(window_hours)
        self.entropy_spike_ratio = float(entropy_spike_ratio)
        self.critical_impact = float(critical_impact)
        self._physics = SystemicFragilityEngine()

    # ── Alert normalisation ───────────────────────────────────────────────

    def normalize_alert(
        self,
        alert: Any,
        *,
        pro_domain_id: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        label: str = "",
    ) -> Optional[AlertGeoEvent]:
        use_lat = lat if lat is not None else getattr(alert, "location_lat", None)
        use_lon = lon if lon is not None else getattr(alert, "location_lng", None)
        if use_lat is None or use_lon is None:
            return None
        try:
            use_lat_f = float(use_lat)
            use_lon_f = float(use_lon)
        except (TypeError, ValueError):
            return None
        if not (-90 <= use_lat_f <= 90 and -180 <= use_lon_f <= 180):
            return None

        ts = getattr(alert, "triggered_at", None) or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        raw = raw_intensity_from_alert(alert)
        omni = omni_domain_for_pro_domain(pro_domain_id)
        return AlertGeoEvent(
            alert_id=str(getattr(alert, "id", "")),
            domain_id=omni,
            lat=use_lat_f,
            lon=use_lon_f,
            raw_intensity=raw,
            ui_intensity=ui_display_intensity(raw),
            triggered_at=ts,
            label=label or str(getattr(alert, "target_label", "") or ""),
        )

    def assign_site_key(self, event: AlertGeoEvent, allowed_keys: Sequence[str]) -> str:
        best_key = allowed_keys[0]
        best_dist = float("inf")
        for key in allowed_keys:
            if key not in GEO_REGISTRY:
                continue
            _, lat, lon, _ = GEO_REGISTRY[key]
            d = _haversine_km(event.lat, event.lon, lat, lon)
            if d < best_dist:
                best_dist = d
                best_key = key
        if best_dist <= MAX_SITE_ASSIGN_KM:
            event.site_key = best_key
            return best_key
        event.site_key = best_key
        return best_key

    # ── Site-level metrics ────────────────────────────────────────────────

    def _historical_entropy_mean(
        self,
        site_key: str,
        domain_id: str,
        prior_nodes: Optional[Dict[Tuple[str, str], float]],
    ) -> float:
        if prior_nodes:
            val = prior_nodes.get((domain_id, site_key))
            if val is not None and val > 0:
                return float(val)
        _, lat, lon, _ = GEO_REGISTRY.get(site_key, ("", 0.0, 0.0, 0.0))
        return 0.35 + 0.15 * self._registry_weight(site_key)

    def _registry_weight(self, site_key: str) -> float:
        return float(GEO_REGISTRY.get(site_key, ("", 0.0, 0.0, 0.5))[3])

    def compute_site_metrics(
        self,
        site_key: str,
        events: List[AlertGeoEvent],
        *,
        domain_id: str,
        prior_nodes: Optional[Dict[Tuple[str, str], float]] = None,
        all_domain_events: Optional[List[AlertGeoEvent]] = None,
    ) -> ComputedSpatialNode:
        name, lat, lon, weight = GEO_REGISTRY[site_key]
        intensities = [e.raw_intensity for e in events if e.raw_intensity > 0]
        ui_vals = [e.ui_intensity for e in events]

        # Frequency + density inside geographic bounding box (24h window).
        box_events = [
            e for e in (all_domain_events or events)
            if _in_bbox(e.lat, e.lon, lat, lon, SITE_BOX_DEG)
        ]
        event_count = len(box_events)
        cluster_density = event_count / max(SITE_BOX_DEG ** 2, 0.01)

        # Shannon entropy on intensity magnitudes (disorder of pressure states).
        entropy_index = self._physics.calculate_network_entropy(intensities or [0.0])
        if event_count >= 2:
            # Blend temporal dispersion: more unique hours → higher entropy.
            hours = {e.triggered_at.replace(minute=0, second=0, microsecond=0) for e in box_events}
            hour_entropy = min(1.0, len(hours) / 12.0)
            entropy_index = float(min(1.0, 0.65 * entropy_index + 0.35 * hour_entropy + 0.1 * min(1.0, cluster_density / 3.0)))

        variance = float(sum((x - (sum(intensities) / len(intensities))) ** 2 for x in intensities) / len(intensities)) if len(intensities) > 1 else (float(intensities[0]) if intensities else 0.0)
        viscosity = self._physics.calculate_kinematic_viscosity(variance, max(event_count, 1))

        hist_mean = self._historical_entropy_mean(site_key, domain_id, prior_nodes)
        phase_transition = hist_mean > 0 and entropy_index >= self.entropy_spike_ratio * hist_mean

        peak_ui = max(ui_vals) if ui_vals else 0.0
        impact = min(99.0, peak_ui * 8.5 + entropy_index * 12.0 + min(20.0, cluster_density * 4.0))
        if phase_transition:
            impact = max(impact, self.critical_impact)

        return ComputedSpatialNode(
            site_key=site_key,
            name=name,
            lat=lat,
            lon=lon,
            impact_score=round(impact, 2),
            entropy_index=round(entropy_index, 4),
            viscosity_coefficient=round(viscosity, 4),
            is_epicenter=False,
            phase_transition_warning=phase_transition,
            event_count=event_count,
            cluster_density=round(cluster_density, 4),
        )

    def build_domain_graph(
        self,
        domain_id: str,
        events: List[AlertGeoEvent],
        *,
        prior_nodes: Optional[Dict[Tuple[str, str], float]] = None,
    ) -> DomainSpatialGraph:
        allowed = DOMAIN_SITE_KEYS.get(domain_id, tuple(GEO_REGISTRY.keys()))
        by_site: Dict[str, List[AlertGeoEvent]] = {k: [] for k in allowed}

        for ev in events:
            key = self.assign_site_key(ev, allowed)
            by_site.setdefault(key, []).append(ev)

        nodes: List[ComputedSpatialNode] = []
        for key in allowed:
            site_events = by_site.get(key, [])
            if not site_events and key != allowed[0]:
                # Keep chokepoint anchors visible with baseline physics.
                site_events = []
            node = self.compute_site_metrics(
                key,
                site_events,
                domain_id=domain_id,
                prior_nodes=prior_nodes,
                all_domain_events=events,
            )
            nodes.append(node)

        if not nodes:
            return DomainSpatialGraph(domain_id=domain_id)

        # Epicenter = highest composite score (entropy × impact weight).
        def _rank(n: ComputedSpatialNode) -> float:
            return n.entropy_index * (n.impact_score / 100.0) * self._registry_weight(n.site_key)

        epicenter = max(nodes, key=_rank)
        for n in nodes:
            n.is_epicenter = n.site_key == epicenter.site_key

        edges = self._build_edges(domain_id, nodes, epicenter.site_key)
        mean_e = sum(n.entropy_index for n in nodes) / len(nodes)
        mean_v = sum(n.viscosity_coefficient for n in nodes) / len(nodes)
        domain_warning = any(n.phase_transition_warning for n in nodes)

        return DomainSpatialGraph(
            domain_id=domain_id,
            nodes=nodes,
            edges=edges,
            phase_transition_warning=domain_warning,
            mean_entropy=round(mean_e, 4),
            mean_viscosity=round(mean_v, 4),
        )

    def _build_edges(
        self,
        domain_id: str,
        nodes: List[ComputedSpatialNode],
        epicenter_key: str,
    ) -> List[ComputedSpatialEdge]:
        node_by_key = {n.site_key: n for n in nodes}
        edges: List[ComputedSpatialEdge] = []
        seen: set[Tuple[float, float, float, float]] = set()

        def _add(src: ComputedSpatialNode, tgt: ComputedSpatialNode, order: int, base: float) -> None:
            key = (src.lat, src.lon, tgt.lat, tgt.lon)
            if key in seen:
                return
            seen.add(key)
            decay = max(0.25, 1.0 - 0.12 * (order - 1))
            intensity = base * decay * (0.5 + 0.5 * src.entropy_index) * (tgt.impact_score / 100.0)
            viscosity = (src.viscosity_coefficient + tgt.viscosity_coefficient) / 2.0
            edges.append(
                ComputedSpatialEdge(
                    source_lat=src.lat,
                    source_lon=src.lon,
                    target_lat=tgt.lat,
                    target_lon=tgt.lon,
                    edge_intensity=round(min(1.0, intensity), 4),
                    viscosity_coefficient=round(viscosity, 4),
                    order_level=order,
                )
            )

        topo = DOMAIN_EDGE_TOPOLOGY.get(domain_id, [])
        for src_key, tgt_key, order, base_int in topo:
            src = node_by_key.get(src_key)
            tgt = node_by_key.get(tgt_key)
            if src and tgt:
                _add(src, tgt, order, base_int)

        # Order-3 systemic ripples: epicenter → flagship cities of affected countries.
        epi = node_by_key.get(epicenter_key)
        if epi:
            for iso, city in list(_ISO_TO_MAJOR_CITY.items())[:3]:
                # Resolve via registry name match when possible.
                tgt_key = None
                for k, (name, lat, lon, _) in GEO_REGISTRY.items():
                    if city.casefold() in name.casefold():
                        tgt_key = k
                        break
                if tgt_key and tgt_key in node_by_key and tgt_key != epicenter_key:
                    _add(epi, node_by_key[tgt_key], 3, 0.35)

        return edges


def prior_entropy_index_map(nodes: Iterable[Any]) -> Dict[Tuple[str, str], float]:
    """Build lookup from existing SpatialNode rows before cleanup."""
    out: Dict[Tuple[str, str], float] = {}
    for n in nodes:
        domain_id = str(getattr(n, "domain_id", "") or "")
        # Reverse-map coords to nearest registry site.
        best_key = None
        best_d = float("inf")
        for key, (_, lat, lon, _) in GEO_REGISTRY.items():
            d = _haversine_km(float(n.lat), float(n.lon), lat, lon)
            if d < best_d:
                best_d = d
                best_key = key
        if best_key:
            out[(domain_id, best_key)] = float(getattr(n, "entropy_index", 0.0) or 0.0)
    return out
