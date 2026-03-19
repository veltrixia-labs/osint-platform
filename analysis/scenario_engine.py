def generate_scenarios(avg_score: float, forecasts: list) -> dict:
    """Generates base, escalation, and containment scenarios with conditional phrasing."""
    
    # Base logic: use top forecast implication if available
    implication = forecasts[0]["implication"] if forecasts else "the current operational environment remains stable"
    implication = implication.lower().rstrip('.')
    
    scenarios = {
        "base": {
            "text": f"If current regional trends persist, then {implication}. Strategic monitoring of development intensity remains the primary analyst response.",
            "confidence": "Medium"
        },
        "escalation": {
            "text": "If geopolitical tensions or supply constraints broaden unexpectedly, then risk profiles will shift toward systemic instability across adjacent sectors.",
            "confidence": "Low"
        },
        "containment": {
            "text": "If diplomatic or regulatory interventions are successfully implemented, then the impact on global markets and regional stability will likely be mitigated.",
            "confidence": "Low"
        }
    }
    
    # Adjust base confidence if signal is very high
    if avg_score > 4.5:
        scenarios["base"]["confidence"] = "High"
        scenarios["escalation"]["confidence"] = "Medium"
        
    return scenarios
