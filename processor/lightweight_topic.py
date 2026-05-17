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
    if raw_topic and raw_topic in STRATEGIC_TOPICS:
        return raw_topic
    if source_group and source_group in STRATEGIC_TOPICS:
        return source_group

    lowered = (text or "").lower()
    best_code = DEFAULT_STRATEGIC_TOPIC
    best_hits = 0
    for code, keywords in TOPIC_KEYWORD_RULES:
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best_hits = hits
            best_code = code
    return best_code
