"""
Keyword-based topic inference (no LLM). Used by normalize + alert pipeline.
"""
from __future__ import annotations

STRATEGIC_TOPICS = frozenset({
    "energy_resource_risk",
    "global_market_intelligence",
    "crypto_geopolitics",
    "ai_semiconductor_intelligence",
    "defense_technology",
    "supply_chain_intelligence",
})

# RSS source_group (config/rss_sources.yaml) → internal topic code
SOURCE_GROUP_TO_TOPIC: dict[str, str] = {
    "crypto": "crypto_geopolitics",
    "energy_resources": "energy_resource_risk",
    "energy": "energy_resource_risk",
    "market_macro": "global_market_intelligence",
    "market": "global_market_intelligence",
    "global_news": "global_market_intelligence",
    "ai_semiconductor": "ai_semiconductor_intelligence",
    "ai": "ai_semiconductor_intelligence",
    "tech": "ai_semiconductor_intelligence",
    "defense": "defense_technology",
    "supply_chain": "supply_chain_intelligence",
    "trade": "supply_chain_intelligence",
    "policy_institutions": "global_market_intelligence",
    "central_banks": "global_market_intelligence",
    "regulators": "global_market_intelligence",
}

TOPIC_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("energy_resource_risk", ("oil", "gas", "lng", "energy", "pipeline", "mining", "crude", "opec")),
    ("supply_chain_intelligence", ("ship", "shipping", "port", "freight", "logistics", "supply chain", "container")),
    ("defense_technology", ("defense", "military", "missile", "navy", "army", "drone", "nato", "war")),
    ("ai_semiconductor_intelligence", ("ai", "semiconductor", "chip", "gpu", "data center", "nvidia", "tsmc")),
    # Crypto before broad market keywords so "crypto market" stays CRYPTO
    ("crypto_geopolitics", ("bitcoin", "crypto", "stablecoin", "blockchain", "ethereum", "defi", "binance")),
    ("global_market_intelligence", ("fed", "inflation", "recession", "gdp", "stocks", "bond", "yield", "market")),
)

DEFAULT_STRATEGIC_TOPIC = "global_market_intelligence"


def infer_topic_from_text(
    text: str,
    *,
    raw_topic: str | None = None,
    source_group: str | None = None,
) -> str:
    """Infer a strategic topic code from title/summary text (no LLM)."""
    if raw_topic:
        rt = raw_topic.strip()
        if rt in STRATEGIC_TOPICS:
            return rt
        from processor.topic_registry import normalize_canonical_topic, STRATEGIC_TO_INTERNAL

        canonical = normalize_canonical_topic(rt)
        if canonical in STRATEGIC_TO_INTERNAL:
            return STRATEGIC_TO_INTERNAL[canonical]

    if source_group:
        sg = source_group.strip().lower()
        if sg in SOURCE_GROUP_TO_TOPIC:
            return SOURCE_GROUP_TO_TOPIC[sg]
        if sg in STRATEGIC_TOPICS:
            return sg

    lowered = (text or "").lower()
    best_code = DEFAULT_STRATEGIC_TOPIC
    best_hits = 0
    for code, keywords in TOPIC_KEYWORD_RULES:
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best_hits = hits
            best_code = code
    return best_code
