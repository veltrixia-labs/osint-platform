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
        "semiconductor", "chip", "gpu", "data center", "nvidia", "tsmc",
    )),
    # Crypto before broad market keywords so "crypto market" stays CRYPTO
    ("crypto_geopolitics", ("bitcoin", "crypto", "stablecoin", "blockchain", "ethereum", "defi", "binance")),
    ("global_market_intelligence", ("fed", "inflation", "recession", "gdp", "stock", "bond", "yield", "market")),
)

DEFAULT_STRATEGIC_TOPIC = "global_market_intelligence"

# Precompiled WORD-BOUNDARY matchers per domain. `\b` stops short tokens (e.g.
# "war", "oil", "ship", and the removed "ai") matching as substrings inside
# unrelated words ("toward", "spoiled", "leadership", "Ukraine"). Compiled once.
# `s?` tolerates the regular plural (missile→missiles, chip→chips, port→ports) so a
# real strategic story is never DROPPED for a singular/plural keyword mismatch now
# that the blind default is gone. `\b` still blocks substring bleed (war≠warning).
_TOPIC_KEYWORD_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (code, tuple(re.compile(r"\b" + re.escape(kw) + r"s?\b", re.IGNORECASE) for kw in keywords))
    for code, keywords in TOPIC_KEYWORD_RULES
)

# ── Non-strategic NOISE guardrail (media / entertainment / celebrity / sports) ──
# An OSINT feed must INGEST ONLY WHAT'S CLASSIFIABLE: general media/entertainment
# stories (e.g. "60 Minutes correspondent fired by CBS") must be dropped at the
# gate, never force-fit into a strategic domain. STRONG = drop on a single hit;
# WEAK = drop on >=2 (terms that are ambiguous alone, like "60 minutes" or
# "correspondent", so a strategic "60 Minutes Iran interview" with one such term
# is NOT dropped).
_NOISE_STRONG = (
    "box office", "red carpet", "film festival", "movie premiere", "premiere night",
    "emmy", "oscar", "academy award", "grammy", "golden globe", "bafta", "tony award",
    "hollywood", "celebrity", "paparazzi", "reality tv", "reality show", "sitcom",
    "late-night show", "late night show", "boy band",
    # sports (high-confidence)
    "world cup", "fifa", "uefa", "premier league", "la liga", "champions league",
    "ballon d'or", "wimbledon", "grand slam", "olympic", "super bowl", "messi",
    "ronaldo", "midfielder", "goalkeeper", "test match", "nba finals", "world series",
)
_NOISE_WEAK = (
    "60 minutes", "broadcaster", "correspondent", "news anchor", "tv anchor",
    "talk show", "tv show", "tv series", "streaming series", "miniseries", "episode",
    "season finale", "showrunner", "screenplay", "actor", "actress", "singer",
    "rapper", "pop star", "album", "film studio", "netflix", "hbo", "disney+",
    "hulu", "showtime",
    # sports (weak)
    "football", "soccer", "tournament", "league", "striker", "transfer fee",
    "squad", "playoff",
)
_NOISE_STRONG_RE = [re.compile(r"\b" + re.escape(t) + r"s?\b", re.IGNORECASE) for t in _NOISE_STRONG]
_NOISE_WEAK_RE = [re.compile(r"\b" + re.escape(t) + r"s?\b", re.IGNORECASE) for t in _NOISE_WEAK]

# Generic / institutional feeds that MUST NOT confer a strategic domain by feed
# alone — their items are content-classified or dropped, never blind-routed.
_GENERIC_SOURCE_GROUPS = frozenset({
    "global_news", "news", "world_news", "top_news", "general",
    "policy_institutions", "central_banks", "regulators",
})


def is_non_strategic_noise(text: str) -> bool:
    """True when the text is general media / entertainment / celebrity / sports
    noise that should be dropped before an alert is ever minted."""
    if not text:
        return False
    if any(p.search(text) for p in _NOISE_STRONG_RE):
        return True
    return sum(1 for p in _NOISE_WEAK_RE if p.search(text)) >= 2


def infer_topic_from_text(
    text: str,
    *,
    title: str | None = None,
    raw_topic: str | None = None,
    source_group: str | None = None,
    strict: bool = False,
) -> str | None:
    """Infer a strategic topic code from title/summary text (no LLM).

    Returns None when the item is non-strategic NOISE or carries no real signal —
    but ONLY in `strict` mode (the ingestion gate, where we DROP such items). Non-
    strict callers (post-ingestion signal / backfill paths) keep the legacy
    DEFAULT_STRATEGIC_TOPIC fallback for back-compat. When `title` is supplied the
    minimum-signal rule applies (a keyword in the TITLE, or >=2 distinct keyword
    hits, before a content domain is assigned)."""
    unclassified = None if strict else DEFAULT_STRATEGIC_TOPIC

    # 0. NON-STRATEGIC NOISE (media / entertainment / sports) → drop at the gate,
    #    before anything can force-fit it into a strategic domain.
    if is_non_strategic_noise(text or ""):
        return unclassified

    # 1. An explicit strategic topic always wins.
    if raw_topic:
        rt = raw_topic.strip()
        if rt in STRATEGIC_TOPICS:
            return rt
        from processor.topic_registry import normalize_canonical_topic, STRATEGIC_TO_INTERNAL

        canonical = normalize_canonical_topic(rt)
        if canonical in STRATEGIC_TO_INTERNAL:
            return STRATEGIC_TO_INTERNAL[canonical]

    # 2. CONTENT-FIRST with a MINIMUM SIGNAL: a keyword in the TITLE, or >=2 distinct
    #    keyword hits overall. A lone incidental term in a long summary no longer
    #    classifies (that was the false-positive vector). Runs BEFORE source_group,
    #    so a missile / chip / bitcoin story still lands in Defense / AI / Crypto.
    lowered = (text or "").lower()
    title_low = (title or "").lower()
    best_code: str | None = None
    best_hits = 0
    best_title_hit = False
    for code, patterns in _TOPIC_KEYWORD_PATTERNS:
        # Tie-break preserved: first domain (rule order) to reach the max wins.
        hits = sum(1 for p in patterns if p.search(lowered))
        if hits > best_hits:
            best_hits = hits
            best_code = code
            # With a title we require the signal to be in the title (else >=2 total);
            # without a title (signal/backfill callers) any hit counts as before.
            best_title_hit = any(p.search(title_low) for p in patterns) if title else (hits >= 1)
    if best_code and (best_title_hit or best_hits >= 2):
        return best_code

    # 3. DOMAIN-SPECIFIC source-group fallback ONLY. A generic feed (global_news,
    #    central_banks, …) must NEVER confer a strategic domain by feed alone.
    if source_group:
        sg = source_group.strip().lower()
        if sg not in _GENERIC_SOURCE_GROUPS:
            mapped = SOURCE_GROUP_TO_TOPIC.get(sg)
            if mapped:
                return mapped
            if sg in STRATEGIC_TOPICS:
                return sg

    # 4. No strategic signal and no domain feed → UNCLASSIFIED (dropped in strict mode).
    return unclassified
