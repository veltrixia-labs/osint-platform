def generate_scenarios(avg_score: float, forecasts: list) -> dict:
    """Generates concrete operational scenarios with prioritized action objects."""
    
    # 1. Component Extraction
    primary_impl = forecasts[0]["implication"] if forecasts else "the current operational environment remains stable"
    primary_impl = primary_impl.lower().rstrip('.')
    
    # 2. Domain Mapping (Map implication to concrete outcome nouns)
    domain_map = {
        "energy": ["supply disruption", "price volatility", "shipping route pressure"],
        "supply": ["logistics delays", "sourcing friction", "inventory gaps"],
        "cyber": ["service disruption", "data exposure", "regulatory pressure"],
        "market": ["market instability", "pricing pressure", "investor sentiment shifts"],
        "geopolitics": ["operational friction", "sanction pressure", "regional instability"]
    }
    
    outcome = "operational friction" # Default
    for domain, terms in domain_map.items():
        if domain in primary_impl:
            outcome = terms[0]
            break

    # 3. Scenario Construction
    # Base: Concrete continuation + Monitor cue
    base_text = (
        f"If current trends continue, expect {primary_impl}, with limited immediate disruption to global markets.\n"
        f"→ Continue monitoring, but no urgent action required."
    )

    # Escalation: Structured bullets + Prepare cue
    esc_terms = domain_map.get(next((d for d in domain_map if d in primary_impl), "geopolitics"), ["systemic friction"])
    
    esc_text = (
        f"If tensions escalate, expect:\n"
        f"* acute {esc_terms[0]}\n"
        f"* increased {esc_terms[1] if len(esc_terms) > 1 else 'market instability'}\n"
        f"* spillover risk into adjacent sectors\n"
        f"→ Prepare for short-term operational volatility and evaluate exposure."
    )

    # Containment: Concrete benefit + Baseline cue
    cont_text = (
        f"If diplomatic or regulatory efforts succeed, {outcome} will stabilize and market volatility will decrease.\n"
        f"→ No immediate action required; maintain monitoring."
    )

    # 4. Structured Actions with explicit Priority and Rationale
    # Note: Rationale provides the "why" for the assigned priority
    scenarios = {
        "base": {
            "text": base_text, 
            "confidence": "Medium", 
            "actions": [
                {
                    "text": "Monitor key indicators for shift in baseline volatility.", 
                    "priority": "Monitor",
                    "rationale": f"because {outcome} remains localized but requires oversight"
                }
            ]
        },
        "escalation": {
            "text": esc_text, 
            "confidence": "Low", 
            "actions": [
                {
                    "text": f"Evaluate exposure to {outcome} and affected supply routes.", 
                    "priority": "High Priority",
                    "rationale": f"due to rising {outcome} risk in key transit nodes"
                },
                {
                    "text": "Prepare contingency plans for sector-wide volatility.", 
                    "priority": "Monitor",
                    "rationale": "as spillover risk into adjacent sectors is increasing"
                }
            ]
        },
        "containment": {
            "text": cont_text, 
            "confidence": "Low", 
            "actions": [
                {
                    "text": "Maintain standard regional tracking; no tactical shift required.", 
                    "priority": "Maintain",
                    "rationale": "as diplomatic success would likely stabilize the domain"
                }
            ]
        }
    }
    
    # 5. Confidence Scaling
    if avg_score > 4.5:
        scenarios["base"]["confidence"] = "High"
        scenarios["escalation"]["confidence"] = "Medium"
        
    return scenarios
