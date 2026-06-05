"""
Keyword-based topic inference (no LLM). Used by normalize + alert pipeline.
"""
from __future__ import annotations

import re

STRATEGIC_TOPICS = frozenset({
    "energy_resource_risk",
    "global_market_intelligence",
    "crypto_geopolitics",
    "ai_semiconductor_intelligence",
    "defense_technology",
    "supply_chain_intelligence",
})

# RSS source_group (config/rss_sources.yaml) → internal topic code.
# Used ONLY as a fallback when content keywords give no signal — and ONLY for
# domain-specific groups. The high-volume GENERIC / INSTITUTIONAL groups
# (global_news, policy_institutions, central_banks, regulators) are deliberately
# omitted: their articles MUST be content-classified so a Defense / Crypto / AI
# story from a general-news feed is credited to its true domain, not blind-routed
# to Markets.
SOURCE_GROUP_TO_TOPIC: dict[str, str] = {
    "crypto": "crypto_geopolitics",
    "energy_resources": "energy_resource_risk",
    "energy": "energy_resource_risk",
    "market_macro": "global_market_intelligence",
    "market": "global_market_intelligence",
    "ai_semiconductor": "ai_semiconductor_intelligence",
    "ai": "ai_semiconductor_intelligence",
    "tech": "ai_semiconductor_intelligence",
    "defense": "defense_technology",
    "supply_chain": "supply_chain_intelligence",
    "trade": "supply_chain_intelligence",
}

TOPIC_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("energy_resource_risk", ("oil", "gas", "lng", "energy", "pipeline", "mining", "crude", "opec")),
    # Phase 7.4 — agricultural commodities + fertilizer feedstocks (phosphate,
    # sulphur, potash, urea, ammonia) are strategic supply-chain inputs;
    # route them into supply_chain_intelligence so the Omni-Monitor merges
    # them with shipping / freight signals.
    ("supply_chain_intelligence", (
        "ship", "shipping", "port", "freight", "logistics", "supply chain", "container",
        "agriculture", "agricultural", "farming", "grain", "wheat", "corn", "soybean",
        "fertilizer", "fertiliser", "phosphate", "sulphur", "sulfur", "potash",
        "urea", "ammonia",
    )),
    ("defense_technology", ("defense", "military", "missile", "navy", "army", "drone", "nato", "war")),
    # Bare "ai" was dropped — as a 2-letter SUBSTRING it bled into "Ukr-ai-ne",
    # "ai-rstrike", "camp-ai-gn", etc. Use precise, multi-char terms; word-boundary
    # matching (below) keeps them from matching inside unrelated words.
    ("ai_semiconductor_intelligence", (
        "artificial intelligence", "genai", "llm",
        "semiconductor", "chips", "gpu", "data center", "nvidia", "tsmc",
    )),
    # Crypto before broad market keywords so "crypto market" stays CRYPTO
    ("crypto_geopolitics", ("bitcoin", "crypto", "stablecoin", "blockchain", "ethereum", "defi", "binance")),
    ("global_market_intelligence", ("fed", "inflation", "recession", "gdp", "stocks", "bond", "yield", "market")),
)

DEFAULT_STRATEGIC_TOPIC = "global_market_intelligence"

# Precompiled WORD-BOUNDARY matchers per domain. `\b` stops short tokens (e.g.
# "war", "oil", "ship", and the removed "ai") matching as substrings inside
# unrelated words ("toward", "spoiled", "leadership", "Ukraine"). Compiled once.
_TOPIC_KEYWORD_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (code, tuple(re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in keywords))
    for code, keywords in TOPIC_KEYWORD_RULES
)


def infer_topic_from_text(
    text: str,
    *,
    raw_topic: str | None = None,
    source_group: str | None = None,
) -> str:
    """Infer a strategic topic code from title/summary text (no LLM)."""
    # 1. An explicit strategic topic always wins.
    if raw_topic:
        rt = raw_topic.strip()
        if rt in STRATEGIC_TOPICS:
            return rt
        from processor.topic_registry import normalize_canonical_topic, STRATEGIC_TO_INTERNAL

        canonical = normalize_canonical_topic(rt)
        if canonical in STRATEGIC_TO_INTERNAL:
            return STRATEGIC_TO_INTERNAL[canonical]

    # 2. CONTENT-FIRST: the headline/summary decides its own domain. This runs
    #    BEFORE any source_group fallback, so a missile / chip / bitcoin story
    #    from a general-news feed lands in Defense / AI / Crypto — not Markets.
    lowered = (text or "").lower()
    best_code: str | None = None
    best_hits = 0
    for code, patterns in _TOPIC_KEYWORD_PATTERNS:
        # Count DISTINCT keywords present (word-boundary), preserving the original
        # tie-break: first domain (in rule order) to reach the max hit-count wins.
        hits = sum(1 for p in patterns if p.search(lowered))
        if hits > best_hits:
            best_hits = hits
            best_code = code
    if best_code:
        return best_code

    # 3. Fallback to a DOMAIN-SPECIFIC source group only (generic/institutional
    #    groups are intentionally absent → they fall through to the default).
    if source_group:
        sg = source_group.strip().lower()
        mapped = SOURCE_GROUP_TO_TOPIC.get(sg)
        if mapped:
            return mapped
        if sg in STRATEGIC_TOPICS:
            return sg

    # 4. Last resort when nothing else matched.
    return DEFAULT_STRATEGIC_TOPIC
