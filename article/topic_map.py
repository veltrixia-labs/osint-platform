# Topic Mapping for OSINT Intelligence Isolation

TOPIC_VOCABULARY = {
    "ai_semiconductor_intelligence": {
        "keywords": ["ai", "semiconductor", "chip", "chips", "gpu", "hbm", "foundry", "tsmc", "nvidia", "asml", "export control", "llm", "wafer", "fab"],
        "label": "AI & Semiconductor"
    },
    "crypto_geopolitics": {
        "keywords": ["crypto", "bitcoin", "stablecoin", "exchange", "sanctions", "wallet", "cbdc", "digital asset", "blockchain", "ethereum", "defi", "sec", "binance", "coinbase"],
        "label": "Crypto & Geopolitics"
    },
    "defense_technology": {
        "keywords": ["missile", "drone", "radar", "satellite", "procurement", "defense industrial base", "electronic warfare", "stealth", "hypersonic", "nato", "uav", "submarine", "frigate"],
        "label": "Defense Technology"
    },
    "supply_chain_intelligence": {
        "keywords": ["shipping", "port", "freight", "logistics", "rerouting", "customs", "maritime", "inventory", "vessel", "container", "baltic", "dry bulk", "supply chain"],
        "label": "Supply Chain Intelligence"
    },
    "energy_resource_risk": {
        "keywords": ["oil", "gas", "lng", "opec", "pipeline", "refinery", "output", "storage", "chokepoint", "crude", "brent", "wti", "gazprom", "aramco"],
        "label": "Energy & Resource Risk"
    },
    "global_market_intelligence": {
        "keywords": ["yields", "inflation", "rates", "liquidity", "central bank", "equities", "futures", "volatility", "fed", "ecb", "boj", "treasury", "sp500"],
        "label": "Global Market Intelligence"
    }
}

def matches_topic(text: str, topic_code: str) -> bool:
    """Checks if a given text matches the controlled vocabulary for a topic."""
    if topic_code not in TOPIC_VOCABULARY:
        return False
    
    text_lower = text.lower()
    keywords = TOPIC_VOCABULARY[topic_code]["keywords"]
    return any(kw in text_lower for kw in keywords)
