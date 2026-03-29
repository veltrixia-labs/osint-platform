
import sys
import os
import re

# Mocking the TrendSignal for verification
class MockTrendSignal:
    def __init__(self, label, description, topic, intensity):
        self.target_label = label
        self.description = description
        self.topic = topic
        self.intensity_score = intensity

BANNED_SURGE_KEYWORDS = [
    "sports", "world cup", "olympics", "football", "basketball", "gaming", "esports",
    "wildlife", "animal rescue", "celebrity", "entertainment", "hollywood", "weather alert",
    "local traffic", "human interest"
]

DOMAIN_BONUS_KEYWORDS = {
    "energy_resource_risk": ["oil", "gas", "lng", "refinery", "pipeline", "opec", "grid", "supply"],
    "geopolitics_intelligence": ["sanctions", "escalation", "diplomatic", "naval", "border", "conflict", "stability", "treaty"],
    "global_market_intelligence": ["equity", "volatility", "interest rate", "fed", "liquidity", "inflation", "asset"],
    "supply_chain_intelligence": ["logistics", "shipping", "port", "congestion", "inventory", "freight"]
}

def calculate_trend_relevance(trend, report_themes, report_category):
    # 1. Hard Exclusions
    t_text = (trend.target_label + " " + (trend.description or "")).lower()
    if any(w in t_text for w in BANNED_SURGE_KEYWORDS):
        return -100 # Permanent rejection
    
    score = 0
    theme_tokens = " ".join(report_themes).lower().split()
    
    # 2. Theme Keyword Match
    for token in theme_tokens:
        if len(token) < 4: continue # Skip short noise
        if token in trend.target_label.lower():
            score += 5
        if trend.description and token in trend.description.lower():
            score += 3
    
    # 3. Domain Alignment
    cat_norm = (report_category or "").lower()
    if trend.topic and cat_norm in trend.topic.lower():
        score += 10
    
    # 4. Sector Bonus
    bonus_words = DOMAIN_BONUS_KEYWORDS.get(cat_norm, [])
    if any(w in t_text for w in bonus_words):
        score += 7

    return score

def verify_relevance():
    print("--- SURGE RELEVANCE VERIFICATION ---")
    
    report_theme = ["Israel energy infrastructure risk", "refinery"]
    report_category = "energy_resource_risk"
    
    signals = [
        MockTrendSignal("Major Refinery Disruption", "Refinery in Haifa reported damage", "energy", 8.0), # Success
        MockTrendSignal("OPEC+ Policy Shift", "OPEC considering new oil quotas", "market", 7.0), # Success (via score/bonus)
        MockTrendSignal("World Cup Finals", "Sports news today", "social", 9.0), # Fail (Banned)
        MockTrendSignal("Wildlife Rescue Mission", "New elephant sanctuary", "social", 5.0), # Fail (Banned)
        MockTrendSignal("Local Traffic Alert", "Accident on Highway 1", "local", 3.0), # Fail (Banned/Low)
        MockTrendSignal("LNG Supply Pressure", "Supply chain bottleneck in pipeline", "energy", 6.5), # Success
        MockTrendSignal("Random Human Interest", "Man finds old coin", "social", 2.0) # Fail (Low score)
    ]
    
    selected = []
    for s in signals:
        score = calculate_trend_relevance(s, report_theme, report_category)
        rejected = score < 5
        status = "REJECTED" if rejected else "ACCEPTED"
        print(f"[{status}] Score: {score:>3} | Label: {s.target_label}")
        if not rejected:
            selected.append(s)

    print(f"\nTotal Selected: {len(selected)} (Expect 3)")
    if len(selected) == 3:
        print("[SUCCESS] Relevance filtering is working as intended.")
    else:
        print("[FAIL] Mismatch in selection logic.")

if __name__ == "__main__":
    verify_relevance()
