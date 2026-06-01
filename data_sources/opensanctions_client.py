"""
OpenSanctions Bulk Dump Ingester.

Strategy: download the daily JSON Lines (FollowTheMoney) dump rather than
hitting their entity API per-record. Free, key-less, and gives us a full
local copy for offline analytics.

Dump endpoint:
    https://data.opensanctions.org/datasets/latest/sanctions/entities.ftm.json
    (~150 MB raw, ~50k entities after filtering)

We stream-parse line-by-line so we never hold the full dump in memory.
Filtering rules (cap the local DB at ~50k rows):
  - keep entity if country code is in G20 + major conflict states
  - drop expired sanctions older than 5 years
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set

import requests

logger = logging.getLogger(__name__)

OPENSANCTIONS_DUMP_URL = (
    "https://data.opensanctions.org/datasets/latest/sanctions/entities.ftm.json"
)

# ISO 3166-1 alpha-2 country codes — G20 + major conflict / sanctioned states.
SANCTIONS_COUNTRY_ALLOWLIST: Set[str] = frozenset({
    # G20
    "us", "gb", "fr", "de", "it", "ca", "jp",       # G7
    "cn", "ru", "in", "br", "au", "kr", "mx",       # rest of G20
    "id", "sa", "tr", "ar", "za", "eu",
    # Major conflict / heavily sanctioned states
    "ir", "kp", "by", "sy", "ve", "cu", "mm", "af", "ye", "sd", "iq", "lb",
    # Frequent supply-chain bottleneck states
    "tw", "sg", "vn", "ae", "qa", "kw", "om",
    # Major OFAC / EU PEP coverage
    "ua", "pl", "il", "ng", "eg", "th", "ph", "my",
})

# OpenSanctions FtM schemas we ingest. Anything else (Address, Sanction objects
# themselves, etc.) we skip — we want named *actors* only.
ACTOR_SCHEMAS: Set[str] = frozenset({
    "Person", "Organization", "Company", "PublicBody", "LegalEntity",
})

# Map an OpenSanctions schema/category to our existing Stakeholder.domain enum.
def _classify_domain(schema: str, topics: Iterable[str]) -> str:
    topic_set = {str(t).lower() for t in topics or []}
    if "sanction" in " ".join(topic_set):
        # Heuristic — sanctions on energy companies fold into energy domain
        if any("oil" in t or "energy" in t or "gas" in t for t in topic_set):
            return "energy_resource_risk"
    if schema == "PublicBody":
        return "defense_technology"
    if any("crypto" in t for t in topic_set):
        return "crypto_geopolitics"
    return "global_market_intelligence"


def _first(v: Any) -> Optional[str]:
    """OpenSanctions properties are arrays; pick the first non-empty value."""
    if isinstance(v, list):
        for item in v:
            if item:
                return str(item)
        return None
    return str(v) if v else None


def _expired(entity: Dict[str, Any], today: date, max_age_years: int = 5) -> bool:
    """Drop sanctions that ended >5 years ago — keep recency for relevance."""
    props = entity.get("properties") or {}
    end_date = _first(props.get("endDate"))
    if not end_date:
        return False
    try:
        ymd = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    age_years = (today - ymd).days / 365.25
    return age_years > max_age_years


def _passes_country_filter(entity: Dict[str, Any]) -> bool:
    props = entity.get("properties") or {}
    countries = props.get("country") or props.get("jurisdiction") or []
    if not isinstance(countries, list):
        countries = [countries]
    for c in countries:
        if isinstance(c, str) and c.strip().lower() in SANCTIONS_COUNTRY_ALLOWLIST:
            return True
    # If no country listed, keep the row — sanctions metadata usually identifies
    # the parties via name lists; we'll let downstream graph pruning handle it.
    return not countries


def normalize_entity(entity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Project an OpenSanctions FtM JSON line into our Stakeholder-compatible dict.
    Returns None if the entity should be skipped.
    """
    if not isinstance(entity, dict):
        return None
    schema = entity.get("schema")
    if schema not in ACTOR_SCHEMAS:
        return None

    props = entity.get("properties") or {}
    name = _first(props.get("name"))
    if not name:
        return None

    country_raw = props.get("country") or props.get("jurisdiction") or []
    if not isinstance(country_raw, list):
        country_raw = [country_raw]
    country = next((str(c).upper() for c in country_raw if c), None)

    topics = props.get("topics") or []
    if not isinstance(topics, list):
        topics = [topics]
    sector = _first(props.get("sector")) or _first(props.get("classification"))
    description = _first(props.get("summary")) or _first(props.get("notes"))

    sanctioned = bool(props.get("sanctions") or props.get("listingDate"))
    sanction_program = _first(props.get("program")) or _first(props.get("authority"))
    pep_score = None
    if "role.pep" in topics or any("pep" in str(t).lower() for t in topics):
        pep_score = 1.0

    return {
        "opensanctions_id": entity.get("id"),
        "schema": schema,
        "name": name,
        "country": country,
        "sector": sector,
        "domain": _classify_domain(schema, topics),
        "description": description,
        "sanctioned_status": sanctioned,
        "sanction_program": sanction_program,
        "pep_score": pep_score,
        "topics": topics,
        "raw": entity,
    }


def stream_dump(
    url: str = OPENSANCTIONS_DUMP_URL,
    *,
    timeout: int = 60,
) -> Iterator[Dict[str, Any]]:
    """
    Stream the JSONL dump line-by-line and yield normalized rows.

    Never holds the full file in memory — designed for ~50k row ingestion
    without spiking RSS on the Render worker.
    """
    today = date.today()
    logger.info("Streaming OpenSanctions dump from %s", url)
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            try:
                entity = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not _passes_country_filter(entity):
                continue
            if _expired(entity, today):
                continue
            normalized = normalize_entity(entity)
            if normalized:
                yield normalized


def stream_entities_from_iter(
    line_iter: Iterable[str],
) -> Iterator[Dict[str, Any]]:
    """
    Test-friendly variant: parse from any iterable of JSON-lines strings
    (e.g. a file handle or in-memory list). Same filtering as `stream_dump`.
    """
    today = date.today()
    for raw_line in line_iter:
        if not raw_line:
            continue
        try:
            entity = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not _passes_country_filter(entity):
            continue
        if _expired(entity, today):
            continue
        normalized = normalize_entity(entity)
        if normalized:
            yield normalized


def extract_relationships(entity: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pull OpenSanctions cross-references (subsidiaries, parents, beneficial owners)
    out of an FtM entity so we can persist them into our Dependency table.
    """
    out: List[Dict[str, Any]] = []
    props = entity.get("raw", {}).get("properties") or {}
    src_id = entity.get("opensanctions_id")
    if not src_id:
        return out

    # OpenSanctions schemas with linkage edges:
    #   ownershipAsset, parent, subsidiaries, associates, beneficialOwners
    for field, kind in (
        ("ownershipAsset",  "subsidiary"),
        ("parent",          "parent"),
        ("subsidiaries",    "subsidiary"),
        ("associates",      "associate"),
        ("beneficialOwners", "owner"),
    ):
        targets = props.get(field) or []
        if not isinstance(targets, list):
            targets = [targets]
        for tgt in targets:
            tgt_id = tgt if isinstance(tgt, str) else None
            if not tgt_id:
                continue
            out.append({
                "source_opensanctions_id": src_id,
                "target_opensanctions_id": tgt_id,
                "dependency_type": kind,
                "exposure_weight": 0.7 if kind == "subsidiary" else 0.5,
            })
    return out
