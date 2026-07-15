"""
Coordinate resolution for alerts.

Extracted from ``jobs/omni_spatial_worker`` so consumers (monthly_trend) don't
depend on the fake spatial worker. Uses the real offline ``GeoLocator``; no
physics-engine involvement.

`resolve_alert_coordinates` and its two helpers are moved here VERBATIM — same
functions, new home. `_GEO_KEYWORDS` is imported from its canonical source
(``pro_structural_context``, the same place the engine sourced it) so the keyword
list stays single-sourced and behaviour is byte-identical.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from analysis.pro_geo_locator import GeoLocator
from analysis.pro_structural_context import _GEO_KEYWORDS
from db.models import AlertLog


def _alert_text_bundle(alert: AlertLog) -> str:
    parts: List[str] = [str(alert.target_label or "")]
    meta = alert.metadata_json
    if isinstance(meta, dict):
        for key in ("location_label", "headline", "title", "summary", "cluster_label"):
            val = meta.get(key)
            if val:
                parts.append(str(val))
    return " ".join(parts)


def _keyword_hits(text: str) -> List[str]:
    if not text:
        return []
    hits: List[str] = []
    lower = text.casefold()
    for kw in _GEO_KEYWORDS:
        if kw.casefold() in lower:
            hits.append(kw)
    return hits


def resolve_alert_coordinates(
    alert: AlertLog,
    geo: GeoLocator,
) -> Optional[Tuple[float, float, str]]:
    """Return (lat, lon, label) or None when no offline resolution is possible."""
    if alert.location_lat is not None and alert.location_lng is not None:
        try:
            lat = float(alert.location_lat)
            lon = float(alert.location_lng)
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon, str(alert.target_label or "")
        except (TypeError, ValueError):
            pass

    bundle = _alert_text_bundle(alert)
    for kw in _keyword_hits(bundle):
        hit = geo.get_coordinates(kw)
        if hit:
            return float(hit["lat"]), float(hit["lon"]), str(hit.get("name") or kw)

    for raw in (alert.target_label, bundle):
        if not raw or len(str(raw).strip()) < 3:
            continue
        hit = geo.get_coordinates(str(raw).strip())
        if hit:
            return float(hit["lat"]), float(hit["lon"]), str(hit.get("name") or raw)

    return None
