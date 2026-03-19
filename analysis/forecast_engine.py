import logging
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

# Rule: (Categorical overlap, Keyword combination) -> (Implication, Confidence, Evidence)
FORECAST_RULES = [
    (
        {"energy_resource_risk", "global_market_intelligence"},
        {"price", "volatility", "supply"},
        "Expect heightened energy price volatility affecting global manufacturing costs.",
        "High",
        "multi-sector overlap + cost keywords"
    ),
    (
        {"defense_technology", "ai_semiconductor_intelligence"},
        {"export", "restriction", "regulation"},
        "Regulatory shifts in semiconductor exports may impact secondary defense supply chains.",
        "Medium",
        "regulatory signal in tech clusters"
    ),
    (
        {"supply_chain_intelligence", "global_market_intelligence"},
        {"maritime", "shipping", "disruption"},
        "Sustained maritime disruptions likely to trigger inflationary pressure on consumer goods.",
        "High",
        "repeated shipping alerts + market weighting"
    ),
    (
        {"crypto_geopolitics"},
        {"sanction", "evasion", "regulation"},
        "Increased focus on digital asset monitoring expected following geopolitical sanction updates.",
        "Medium",
        "sanction-related keywords in crypto context"
    )
]

def generate_forecasts(categories: List[str], all_text: str, avg_score: float) -> List[Dict]:
    """Generates rule-based forecasts based on cluster data."""
    forecasts = []
    cat_set = set(categories)
    text_lower = all_text.lower()
    
    for req_cats, req_kws, impl, base_conf, evidence in FORECAST_RULES:
        # Check category overlap
        if cat_set.intersection(req_cats):
            # Check keyword presence
            match_count = sum(1 for kw in req_kws if kw in text_lower)
            if match_count >= 1:
                # Adjust confidence based on score and match count
                confidence = base_conf
                if avg_score > 4.0 and match_count >= 2:
                    confidence = "High"
                elif avg_score < 2.0:
                    confidence = "Low"
                
                forecasts.append({
                    "implication": impl,
                    "confidence": confidence,
                    "evidence": f"[{evidence}]"
                })
                
    # If no rules match, provide professional analyst baselines
    if not forecasts:
        if avg_score > 3.0:
            forecasts.append({
                "implication": "Continued monitoring of cross-sector impact recommended as signal intensity increases.",
                "confidence": "Medium",
                "evidence": "[high signal baseline]"
            })
        else:
            forecasts.append({
                "implication": "No immediate critical-path implications detected; maintaining standard regional monitoring posture.",
                "confidence": "Low",
                "evidence": "[regional baseline monitoring]"
            })
        
    return forecasts
