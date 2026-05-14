"""
Geographic location resolution from free text using a static entity registry.

Inspired by World Monitor-style entity indexing: word-boundary regex matching,
typed matches (name / alias / keyword), confidence scoring, and best-coordinate
selection for AlertLog.location_lat / location_lng.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

MatchType = Literal["name", "alias", "keyword"]


@dataclass(frozen=True)
class RelatedCompanyRow:
    """
    Optional registry row attached to a static location (Context Briefs).

    JSON ``type`` of ``company`` marks a concrete issuer; otherwise treated as
    an illustrative industry / cluster label.
    """

    name: str
    sector: str
    country: str
    match_basis: str
    ticker: Optional[str] = None
    row_type: str = "industry"


def _escape_regex(s: str) -> str:
    return re.escape(s)


def _slugify(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", label.lower().strip()).strip("-")
    return s or "unknown"


def _parse_related_companies(raw: Any) -> Tuple[RelatedCompanyRow, ...]:
    rows: List[RelatedCompanyRow] = []
    if not isinstance(raw, list):
        return tuple(rows)
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("company_name") or "").strip()
        if not name:
            continue
        sector = str(row.get("sector") or "Unknown").strip()
        country = str(row.get("country") or "Global").strip()
        basis = str(row.get("match_basis") or "Location registry").strip()
        ticker_raw = row.get("ticker")
        ticker = str(ticker_raw).strip() if ticker_raw not in (None, "") else None
        type_raw = str(row.get("type") or "industry").strip().lower()
        row_type = "company" if type_raw == "company" else "industry"
        rows.append(
            RelatedCompanyRow(
                name=name,
                sector=sector,
                country=country,
                match_basis=basis,
                ticker=ticker,
                row_type=row_type,
            )
        )
    return tuple(rows)


def _confidence_for_name_or_alias(match_type: MatchType, matched_text: str) -> float:
    """Higher confidence for longer boundary-safe matches; name slightly above alias."""
    n = len(matched_text.strip())
    if match_type == "name":
        base = 0.88 if n <= 4 else 0.93
        bonus = min(0.06, max(0.0, n - 6) * 0.012)
        return min(0.99, base + bonus)
    # alias
    base = 0.85 if n <= 4 else 0.95
    bonus = min(0.05, max(0.0, n - 6) * 0.01)
    return min(0.98, base + bonus)


def _confidence_for_keyword(matched_text: str) -> float:
    n = len(matched_text.strip())
    base = 0.62
    bonus = min(0.18, max(0.0, n - 3) * 0.022)
    return min(0.85, base + bonus)


@dataclass(frozen=True)
class LocationEntity:
    """
    Extended static location entry (World Monitor EntityEntry–style).

    JSON field ``type`` is mapped to ``entity_type`` (avoids shadowing builtins.type).
    """

    id: str
    name: str
    lat: float
    lng: float
    zoom: Optional[float] = None
    aliases: Tuple[str, ...] = field(default_factory=tuple)
    keywords: Tuple[str, ...] = field(default_factory=tuple)
    entity_type: str = "location"
    sector: Optional[str] = None
    related: Tuple[str, ...] = field(default_factory=tuple)
    related_companies: Tuple[RelatedCompanyRow, ...] = field(default_factory=tuple)

    def coords_tuple(self) -> Tuple[float, float]:
        return (self.lat, self.lng)


@dataclass(frozen=True)
class LocationEntityMatch:
    """A single regex match against the registry (cf. EntityMatch)."""

    entity_id: str
    name: str
    matched_text: str
    match_type: MatchType
    confidence: float
    position: int


@dataclass(frozen=True)
class LocationResolution:
    """Best location pick for persistence (e.g. AlertLog) with audit fields."""

    lat: float
    lng: float
    entity_id: str
    display_name: str
    matched_text: str
    match_type: MatchType
    confidence: float
    position: int


@dataclass
class LocationEntityIndex:
    """Inverted indexes for lookup (cf. entity-index EntityIndex)."""

    by_id: Dict[str, LocationEntity]
    by_alias: Dict[str, str]  # lower(alias) -> entity_id (last write wins, TS parity)
    by_keyword: Dict[str, set]
    by_sector: Dict[str, set]
    by_type: Dict[str, set]

    def get_display_name(self, entity_id: str) -> str:
        e = self.by_id.get(entity_id)
        return e.name if e else entity_id

    def find_related(self, entity_id: str) -> List[LocationEntity]:
        e = self.by_id.get(entity_id)
        if not e or not e.related:
            return []
        out: List[LocationEntity] = []
        for rid in e.related:
            rel = self.by_id.get(rid)
            if rel:
                out.append(rel)
        return out


def build_location_entity_index(entities: List[LocationEntity]) -> LocationEntityIndex:
    by_id: Dict[str, LocationEntity] = {}
    by_alias: Dict[str, str] = {}
    by_keyword: Dict[str, set] = {}
    by_sector: Dict[str, set] = {}
    by_type: Dict[str, set] = {}

    for ent in entities:
        by_id[ent.id] = ent

        for alias in ent.aliases:
            key = alias.strip().lower()
            if key:
                by_alias[key] = ent.id
        by_alias[ent.id.lower()] = ent.id
        by_alias[ent.name.strip().lower()] = ent.id

        for kw in ent.keywords:
            k = kw.strip().lower()
            if not k:
                continue
            by_keyword.setdefault(k, set()).add(ent.id)

        if ent.sector:
            sec = ent.sector.strip().lower()
            if sec:
                by_sector.setdefault(sec, set()).add(ent.id)

        t = ent.entity_type.strip() if ent.entity_type else "location"
        by_type.setdefault(t, set()).add(ent.id)

    return LocationEntityIndex(
        by_id=by_id,
        by_alias=by_alias,
        by_keyword=by_keyword,
        by_sector=by_sector,
        by_type=by_type,
    )


class StaticLocationEntityLoader:
    """
    Loads static_locations.json supporting:
    - Legacy object map: { "Taiwan": { "lat", "lng", "zoom?", ... }, ... }
    - Wrapped list: { "entities": [ { "id", "name", "lat", "lng", ... }, ... ] }
    """

    def __init__(self, path: str = "processor/static_locations.json"):
        self.path = path

    def load(self) -> List[LocationEntity]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            raw: Any = json.load(f)
        return self.entities_from_raw(raw)

    @staticmethod
    def entities_from_raw(raw: Any) -> List[LocationEntity]:
        if isinstance(raw, dict) and isinstance(raw.get("entities"), list):
            return StaticLocationEntityLoader._parse_entity_list(raw["entities"])
        if isinstance(raw, dict):
            return StaticLocationEntityLoader._parse_legacy_map(raw)
        return []

    @staticmethod
    def _parse_legacy_map(data: Dict[str, Any]) -> List[LocationEntity]:
        entities: List[LocationEntity] = []
        for default_name, payload in data.items():
            if default_name.startswith("_") or not isinstance(payload, dict):
                continue
            lat, lng = payload.get("lat"), payload.get("lng")
            if lat is None or lng is None:
                continue
            name = str(payload.get("name") or default_name)
            eid = str(payload.get("id") or _slugify(name))
            zoom = payload.get("zoom")
            aliases = tuple(
                str(a)
                for a in (payload.get("aliases") or [])
                if isinstance(a, str) and a.strip()
            )
            keywords = tuple(
                str(k)
                for k in (payload.get("keywords") or [])
                if isinstance(k, str) and k.strip()
            )
            typ = str(payload.get("type") or "location")  # JSON key "type"
            sector = payload.get("sector")
            sector_s = str(sector).strip() if sector is not None else None
            related = tuple(
                str(r)
                for r in (payload.get("related") or [])
                if isinstance(r, str) and r.strip()
            )
            related_companies = _parse_related_companies(payload.get("related_companies"))
            entities.append(
                LocationEntity(
                    id=eid,
                    name=name,
                    lat=float(lat),
                    lng=float(lng),
                    zoom=float(zoom) if zoom is not None else None,
                    aliases=aliases,
                    keywords=keywords,
                    entity_type=typ,
                    sector=sector_s,
                    related=related,
                    related_companies=related_companies,
                )
            )
        return entities

    @staticmethod
    def _parse_entity_list(rows: List[Any]) -> List[LocationEntity]:
        entities: List[LocationEntity] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            lat, lng = row.get("lat"), row.get("lng")
            if lat is None or lng is None:
                continue
            name = str(row.get("name") or row.get("id") or "unknown")
            eid = str(row.get("id") or _slugify(name))
            zoom = row.get("zoom")
            aliases = tuple(
                str(a) for a in (row.get("aliases") or []) if isinstance(a, str) and a.strip()
            )
            keywords = tuple(
                str(k) for k in (row.get("keywords") or []) if isinstance(k, str) and k.strip()
            )
            typ = str(row.get("type") or "location")
            sector = row.get("sector")
            sector_s = str(sector).strip() if sector is not None else None
            related = tuple(
                str(r) for r in (row.get("related") or []) if isinstance(r, str) and r.strip()
            )
            related_companies = _parse_related_companies(row.get("related_companies"))
            entities.append(
                LocationEntity(
                    id=eid,
                    name=name,
                    lat=float(lat),
                    lng=float(lng),
                    zoom=float(zoom) if zoom is not None else None,
                    aliases=aliases,
                    keywords=keywords,
                    entity_type=typ,
                    sector=sector_s,
                    related=related,
                    related_companies=related_companies,
                )
            )
        return entities


def _match_end(m: LocationEntityMatch) -> int:
    return m.position + len(m.matched_text)


def _remove_subspan_matches(candidates: List[LocationEntityMatch]) -> List[LocationEntityMatch]:
    """
    Drop matches whose span is strictly contained in another match's span
    (e.g. 'China' inside 'South China Sea').
    """
    if len(candidates) < 2:
        return candidates
    kept: List[LocationEntityMatch] = []
    for m in candidates:
        ms, me = m.position, _match_end(m)
        dominated = False
        for o in candidates:
            if o is m:
                continue
            os_, oe = o.position, _match_end(o)
            if os_ <= ms and me <= oe and (oe - os_) > (me - ms):
                dominated = True
                break
        if not dominated:
            kept.append(m)
    return kept


def find_location_entities_in_text(
    text: str,
    index: LocationEntityIndex,
    *,
    min_token_len: int = 3,
) -> List[LocationEntityMatch]:
    """
    Find location entities using word-boundary-aware regex (Python re, \\b).

    Match precedence per entity: best single match by confidence, then earliest position.
    Global ordering: confidence desc, position asc (World Monitor–style sort).
    """
    if not text or not index.by_id:
        return []

    matches: List[LocationEntityMatch] = []
    seen_entity: set = set()

    # --- Name & alias: collect all regex hits, drop sub-spans, then one best hit per entity ---
    alias_jobs: List[Tuple[str, str, MatchType]] = []
    for eid, ent in index.by_id.items():
        name_l = ent.name.strip()
        if len(name_l) >= min_token_len:
            alias_jobs.append((name_l.lower(), eid, "name"))
        for al in ent.aliases:
            al_st = al.strip()
            if len(al_st) < min_token_len:
                continue
            if al_st.lower() == name_l.lower():
                continue
            alias_jobs.append((al_st.lower(), eid, "alias"))

    alias_jobs.sort(key=lambda x: len(x[0]), reverse=True)

    name_alias_candidates: List[LocationEntityMatch] = []
    for phrase_lower, eid, mtype in alias_jobs:
        pattern = rf"\b{_escape_regex(phrase_lower)}\b"
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            continue
        for m in rx.finditer(text):
            matched = m.group(0)
            conf = _confidence_for_name_or_alias(mtype, matched)
            name_alias_candidates.append(
                LocationEntityMatch(
                    entity_id=eid,
                    name=index.by_id[eid].name,
                    matched_text=matched,
                    match_type=mtype,
                    confidence=conf,
                    position=m.start(),
                )
            )

    name_alias_candidates = _remove_subspan_matches(name_alias_candidates)
    best_na: Dict[str, LocationEntityMatch] = {}
    for cand in name_alias_candidates:
        cur = best_na.get(cand.entity_id)
        if cur is None or cand.confidence > cur.confidence or (
            cand.confidence == cur.confidence and cand.position < cur.position
        ):
            best_na[cand.entity_id] = cand
    for cand in best_na.values():
        matches.append(cand)
        seen_entity.add(cand.entity_id)

    na_spans: List[Tuple[int, int]] = [(m.position, _match_end(m)) for m in matches]

    def _inside_na_span(start: int, end: int) -> bool:
        for s0, e0 in na_spans:
            if s0 <= start and end <= e0:
                return True
        return False

    # --- Keywords: boundary-aware on full phrase (\\b at edges) ---
    # At most one keyword hit per entity; pick highest-confidence keyword match.
    kw_candidates: List[LocationEntityMatch] = []
    for kw, eids in index.by_keyword.items():
        if len(kw) < min_token_len:
            continue
        pattern = rf"\b{_escape_regex(kw)}\b"
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            continue
        for m in rx.finditer(text):
            matched = m.group(0)
            pos = m.start()
            end = pos + len(matched)
            if _inside_na_span(pos, end):
                continue
            conf = _confidence_for_keyword(matched)
            for eid in eids:
                if eid in seen_entity:
                    continue
                kw_candidates.append(
                    LocationEntityMatch(
                        entity_id=eid,
                        name=index.by_id[eid].name,
                        matched_text=matched,
                        match_type="keyword",
                        confidence=conf,
                        position=pos,
                    )
                )

    # Best keyword match per entity (highest confidence, then earliest)
    best_kw: Dict[str, LocationEntityMatch] = {}
    for km in kw_candidates:
        cur = best_kw.get(km.entity_id)
        if cur is None or km.confidence > cur.confidence or (
            km.confidence == cur.confidence and km.position < cur.position
        ):
            best_kw[km.entity_id] = km
    for km in best_kw.values():
        if km.entity_id not in seen_entity:
            matches.append(km)

    matches.sort(key=lambda x: (-x.confidence, x.position))
    return matches


class LocationResolver:
    """
    Resolves (lat, lng) from text using the static location entity index.
    """

    def __init__(self, static_map_path: str = "processor/static_locations.json"):
        self.static_map_path = static_map_path
        loader = StaticLocationEntityLoader(static_map_path)
        self.entities: List[LocationEntity] = loader.load()
        self.index: LocationEntityIndex = build_location_entity_index(self.entities)

    def reload(self) -> None:
        loader = StaticLocationEntityLoader(self.static_map_path)
        self.entities = loader.load()
        self.index = build_location_entity_index(self.entities)

    def find_entities_in_text(self, text: str) -> List[LocationEntityMatch]:
        """All matches sorted by confidence desc, then position asc."""
        return find_location_entities_in_text(text, self.index)

    def get_entity(self, entity_id: str) -> Optional[LocationEntity]:
        if not entity_id:
            return None
        return self.index.by_id.get(entity_id)

    def resolve_heuristically_detailed(self, text: str) -> Optional[LocationResolution]:
        """
        Best (lat, lng) with metadata for logging or metadata_json.
        """
        matches = self.find_entities_in_text(text)
        if not matches:
            return None
        best_by_entity: Dict[str, LocationEntityMatch] = {}
        for m in matches:
            cur = best_by_entity.get(m.entity_id)
            if cur is None or m.confidence > cur.confidence or (
                m.confidence == cur.confidence and m.position < cur.position
            ):
                best_by_entity[m.entity_id] = m
        finalists = list(best_by_entity.values())
        top = max(finalists, key=lambda x: (x.confidence, -x.position))
        ent = self.index.by_id.get(top.entity_id)
        if not ent:
            return None
        return LocationResolution(
            lat=ent.lat,
            lng=ent.lng,
            entity_id=ent.id,
            display_name=ent.name,
            matched_text=top.matched_text,
            match_type=top.match_type,
            confidence=round(top.confidence, 4),
            position=top.position,
        )

    def resolve_heuristically(self, text: str) -> Optional[Tuple[float, float]]:
        """
        Scan text for known locations from the static entity index.
        Returns (lat, lng) of the highest-confidence boundary-safe match, or None.
        """
        detail = self.resolve_heuristically_detailed(text)
        if not detail:
            return None
        return (detail.lat, detail.lng)

    def resolve_full(self, text: str, llm_client=None) -> Optional[Tuple[float, float]]:
        """
        Hybrid resolution:
        1. Entity index (zero cost)
        2. LLM fallback (only if llm_client is provided/authorized)
        """
        heuristic_hit = self.resolve_heuristically(text)
        if heuristic_hit:
            return heuristic_hit

        if llm_client:
            return self._llm_extract(text, llm_client)

        return None

    def _llm_extract(self, text: str, llm_client) -> Optional[Tuple[float, float]]:
        return None
