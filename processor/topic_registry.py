"""
Canonical alert topic codes (UPPER_SNAKE) for API / UI color mapping.
Internal inference still uses snake_case in lightweight_topic.
"""
from __future__ import annotations

CANONICAL_TOPICS = frozenset({
    "GEOPOLITICS",
    "ENERGY_RESOURCE_RISK",
    "SUPPLY_CHAIN_INTELLIGENCE",
    "AI_SEMICONDUCTOR_INTELLIGENCE",
    "MARKET_SENTIMENT",
    "DEFENSE_TECHNOLOGY",
    "GLOBAL_MARKET_INTELLIGENCE",
})

INTERNAL_TO_CANONICAL: dict[str, str] = {
    "energy_resource_risk": "ENERGY_RESOURCE_RISK",
    "supply_chain_intelligence": "SUPPLY_CHAIN_INTELLIGENCE",
    "defense_technology": "DEFENSE_TECHNOLOGY",
    "crypto_geopolitics": "GEOPOLITICS",
    "ai_semiconductor_intelligence": "AI_SEMICONDUCTOR_INTELLIGENCE",
    "global_market_intelligence": "GLOBAL_MARKET_INTELLIGENCE",
}

# Legacy / alias keys that may already exist in DB rows
_ALIASES: dict[str, str] = {
    "CRYPTO_GEOPOLITICS": "GEOPOLITICS",
    "GLOBAL": "GLOBAL_MARKET_INTELLIGENCE",
}

_MARKET_SENTIMENT_TREND_BASES = frozenset({
    "entity_heat",
    "sector_surge",
    "risk_acceleration",
})


def _normalize_trend_base(trend_type: str | None) -> str:
    if not trend_type:
        return ""
    base = trend_type.strip().lower()
    if base.endswith("_merged"):
        base = base[: -len("_merged")]
    return base.split("(")[0].strip()


def normalize_canonical_topic(
    raw: str | None,
    *,
    trend_type: str | None = None,
) -> str:
    """Map internal or legacy topic strings to a fixed UPPER_SNAKE canonical code."""
    if not raw:
        return "GLOBAL_MARKET_INTELLIGENCE"

    stripped = raw.strip()
    upper = stripped.upper()
    if upper in CANONICAL_TOPICS:
        return upper
    if upper in _ALIASES:
        return _ALIASES[upper]

    lower = stripped.lower()
    if lower in INTERNAL_TO_CANONICAL:
        canon = INTERNAL_TO_CANONICAL[lower]
        if lower == "global_market_intelligence":
            if _normalize_trend_base(trend_type) in _MARKET_SENTIMENT_TREND_BASES:
                return "MARKET_SENTIMENT"
        return canon

    return "GLOBAL_MARKET_INTELLIGENCE"
