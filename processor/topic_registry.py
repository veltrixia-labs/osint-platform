"""
Strategic topic codes (6 sectors) for AlertLog.topic and UI color mapping.
Internal inference still uses snake_case in lightweight_topic.
"""
from __future__ import annotations

STRATEGIC_TOPIC_CODES = frozenset({
    "ENERGY",
    "MARKET",
    "AI_TECH",
    "CRYPTO",
    "DEFENSE",
    "SUPPLY_CHAIN",
})

# Backward-compatible alias for alert_manager checks
CANONICAL_TOPICS = STRATEGIC_TOPIC_CODES

INTERNAL_TO_STRATEGIC: dict[str, str] = {
    "energy_resource_risk": "ENERGY",
    "global_market_intelligence": "MARKET",
    "market_sentiment": "MARKET",
    "geopolitics": "MARKET",
    "crypto_geopolitics": "CRYPTO",
    "ai_semiconductor_intelligence": "AI_TECH",
    "defense_technology": "DEFENSE",
    "supply_chain_intelligence": "SUPPLY_CHAIN",
}

# Legacy / alias keys that may already exist in DB rows
_ALIASES: dict[str, str] = {
    "ENERGY_RESOURCE_RISK": "ENERGY",
    "GLOBAL_MARKET_INTELLIGENCE": "MARKET",
    "MARKET_SENTIMENT": "MARKET",
    "GEOPOLITICS": "MARKET",
    "CRYPTO_GEOPOLITICS": "CRYPTO",
    "AI_SEMICONDUCTOR_INTELLIGENCE": "AI_TECH",
    "DEFENSE_TECHNOLOGY": "DEFENSE",
    "SUPPLY_CHAIN_INTELLIGENCE": "SUPPLY_CHAIN",
    "GLOBAL": "MARKET",
}

# Kept for audit script imports
INTERNAL_TO_CANONICAL = INTERNAL_TO_STRATEGIC


def normalize_canonical_topic(
    raw: str | None,
    *,
    trend_type: str | None = None,
) -> str:
    """Map internal or legacy topic strings to one of 6 strategic UPPER_SNAKE codes."""
    del trend_type  # sentiment trends fold into MARKET
    if not raw:
        return "MARKET"

    stripped = raw.strip()
    upper = stripped.upper().replace("-", "_")
    if upper in STRATEGIC_TOPIC_CODES:
        return upper
    if upper in _ALIASES:
        return _ALIASES[upper]

    lower = stripped.lower()
    if lower in INTERNAL_TO_STRATEGIC:
        return INTERNAL_TO_STRATEGIC[lower]

    if "ENERGY" in upper or "OIL" in upper or "GAS" in upper:
        return "ENERGY"
    if "SUPPLY" in upper or "TRADE" in upper or "LOGISTIC" in upper:
        return "SUPPLY_CHAIN"
    if "CRYPTO" in upper or "BITCOIN" in upper:
        return "CRYPTO"
    if "DEFENSE" in upper or "MILITARY" in upper:
        return "DEFENSE"
    if "SEMICONDUCTOR" in upper or upper.startswith("AI"):
        return "AI_TECH"
    if "MARKET" in upper or "GEOPOLIT" in upper or "GLOBAL" in upper:
        return "MARKET"

    return "MARKET"
