"""
Location-linked context for Free-tier Context Briefs.

Builds supplemental company/infrastructure rows from static location registry
(`related`, `related_companies`) plus topic-based illustrative fallbacks when
rule-based news matching yields no companies.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from processor.location_resolver import LocationResolver
from processor.topic_registry import internal_topic_for_fallback

# Topic code -> illustrative (name, sector, country, match_basis) rows
TOPIC_SECTOR_FALLBACK: Dict[str, Tuple[Tuple[str, str, str, str], ...]] = {
    "energy_resource_risk": (
        ("VLCC / crude tanker operators (cluster)", "Marine transport", "Global", "Sector context — energy logistics & chokepoints (illustrative)"),
        ("Integrated oil & gas majors", "Energy", "Global", "Sector context — upstream/downstream exposure (illustrative)"),
        ("Independent refiners & petrochemical buyers", "Refining & chemicals", "Global", "Sector context — crude price pass-through (illustrative)"),
    ),
    "global_market_intelligence": (
        ("Global banks & market makers", "Financial services", "Global", "Sector context — rates, FX, risk assets (illustrative)"),
        ("Asset managers / pension overlays", "Asset management", "Global", "Sector context — cross-asset hedging (illustrative)"),
    ),
    "crypto_geopolitics": (
        ("Crypto exchanges & custodians", "Digital assets", "Global", "Sector context — liquidity & regulatory perimeter (illustrative)"),
        ("Stablecoin issuers & payment fintechs", "Payments", "Global", "Sector context — settlement rails (illustrative)"),
    ),
    "defense_technology": (
        ("Prime defense contractors", "Aerospace & defense", "Global", "Sector context — procurement cycles (illustrative)"),
        ("Defense electronics suppliers", "Electronics", "Global", "Sector context — mission systems supply chain (illustrative)"),
    ),
    "supply_chain_intelligence": (
        ("Container lines & freight forwarders", "Logistics", "Global", "Sector context — lane disruption sensitivity (illustrative)"),
        ("Industrial distributors & EMS providers", "Industrials", "Global", "Sector context — component lead times (illustrative)"),
    ),
    "ai_semiconductor_intelligence": (
        ("Semiconductor foundries & IDMs", "Semiconductors", "Global", "Sector context — fab utilization & capex (illustrative)"),
        ("Equipment & materials suppliers", "Semiconductor capital equipment", "Global", "Sector context — process node ramps (illustrative)"),
    ),
}


def topic_sector_fallback_rows(topic: str | None) -> Tuple[Tuple[str, str, str, str], ...]:
    """Resolve strategic (ENERGY, …) or legacy topic codes to illustrative sector rows."""
    legacy_key = internal_topic_for_fallback(topic)
    return TOPIC_SECTOR_FALLBACK.get(legacy_key, ())


def _impact_dict(
    name: str,
    sector: str,
    country: str,
    basis: str,
    *,
    ticker: Optional[str] = None,
    registry_entity_type: Optional[str] = None,
    internal_score: float = 0.55,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "company_name": name,
        "ticker": ticker,
        "sector": sector,
        "country": country,
        "match_basis": [basis],
        "related_news_count": 0,
        "top_related_news": [],
        "_internal_score": internal_score,
    }
    if registry_entity_type:
        row["registry_entity_type"] = registry_entity_type
    return row


def build_location_company_supplement(
    alert_log: Any,
    resolver: LocationResolver,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Returns (supplemental_company_impacts, location_context_dict) for merging
    into Free Alert feed generation.
    """
    meta: Dict[str, Any] = getattr(alert_log, "metadata_json", None) or {}
    if not isinstance(meta, dict):
        meta = {}

    entity_id: Optional[str] = meta.get("location_entity_id")
    text = f"{getattr(alert_log, 'target_label', '') or ''} {meta.get('description', '') or ''}".strip()
    if not entity_id and text:
        det = resolver.resolve_heuristically_detailed(text)
        entity_id = det.entity_id if det else None

    ctx: Dict[str, Any] = {
        "location_entity_id": entity_id,
        "resolved_entity_name": None,
        "related_geographies": [],
        "registry_company_rows": 0,
        "registry_related_company_total": 0,
        "registry_catalog_total": 0,
        "source": "none",
    }
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()

    ent = resolver.get_entity(entity_id) if entity_id else None
    if ent:
        ctx["resolved_entity_name"] = ent.name
        related_geo_list = list(resolver.index.find_related(ent.id))
        ctx["registry_related_company_total"] = len(ent.related_companies)
        ctx["registry_catalog_total"] = len(ent.related_companies) + len(related_geo_list)

        for rc in ent.related_companies:
            key = rc.name.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            reg_type = "company" if rc.row_type == "company" else "industry"
            score = 0.72 if reg_type == "company" else 0.58
            rows.append(
                _impact_dict(
                    rc.name,
                    rc.sector,
                    rc.country,
                    rc.match_basis,
                    ticker=rc.ticker,
                    registry_entity_type=reg_type,
                    internal_score=score,
                )
            )
        ctx["registry_company_rows"] = len(ent.related_companies)

        for rel in related_geo_list:
            ctx["related_geographies"].append(
                {"id": rel.id, "name": rel.name, "entity_type": rel.entity_type, "sector": rel.sector}
            )
            gkey = f"geo:{rel.name.strip().lower()}"
            if gkey in seen:
                continue
            seen.add(gkey)
            rows.append(
                _impact_dict(
                    rel.name,
                    rel.entity_type or "Geography",
                    "—",
                    f"Linked geography — {rel.sector or 'regional'} context",
                    registry_entity_type=rel.entity_type or None,
                )
            )

    if rows:
        ctx["source"] = "location_registry"
        return rows, ctx

    topic = getattr(alert_log, "topic", None) or ""
    for tup in topic_sector_fallback_rows(topic):
        key = tup[0].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(_impact_dict(tup[0], tup[1], tup[2], tup[3]))

    if rows:
        ctx["source"] = "sector_fallback"
    return rows, ctx
