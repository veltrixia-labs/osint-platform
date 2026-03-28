def generate_scenarios(avg_score: float, forecasts: list) -> dict:
    """Generates concrete operational scenarios with prioritized action objects."""
    
    # 1. Component Extraction
    primary_impl = forecasts[0]["implication"] if forecasts else "current trends continue"
    primary_impl = primary_impl.lower().rstrip('.')
    
    # 2. Domain Mapping (Strictly concrete real-world outcomes)
    domain_map = {
        "geopolitics": ["sanctions pressure", "route instability", "supply disruptions", "border delays"],
        "energy": ["price volatility", "supply gaps", "route pressure", "refinery bottlenecks"],
        "supply": ["bottlenecks", "shipping delays", "inventory pressure", "logistics friction"],
        "cyber": ["service disruption", "data exposure", "regulatory scrutiny", "access delays"],
        "market": ["volatility spikes", "liquidity shifts", "spillover into adjacent sectors", "pricing pressure"]
    }
    
    # Identify the primary domain and outcomes
    active_domain = next((d for d in domain_map if d in primary_impl), "geopolitics")
    outcomes = domain_map.get(active_domain)
    
    # 3. Scenario Construction (Strict: If [cond], expect:\n* [out1]\n* [out2]\n→ [action])
    
    # Base Case: Continuation logic
    base_text = (
        f"If {primary_impl}, expect:\n"
        f"* continued {outcomes[0]}\n"
        f"* gradual {outcomes[1]}\n"
        f"→ Continue monitoring {active_domain} supply routes and pricing signals."
    )
    
    # Escalation Case: High-Urgency logic
    esc_trigger = f"escalation signals for {active_domain} increase" if "geopolitics" in active_domain else f"{active_domain} tensions escalate"
    esc_text = (
        f"If {esc_trigger}, expect:\n"
        f"* acute {outcomes[0]}\n"
        f"* increased {outcomes[2]}\n"
        f"* {outcomes[3] if len(outcomes) > 3 else 'heightened market instability'}\n"
        f"→ Prepare for short-term {outcomes[1]} and review exposure."
    )
    
    # Containment Case: Stabilization logic
    cont_text = (
        f"If stabilization measures for {active_domain} succeed, expect:\n"
        f"* {outcomes[1].replace('pressure', 'stabilization').replace('volatility', 'stabilization').replace('delays', 'reduction').replace('friction', 'easing').replace('gaps', 'closure')}\n"
        f"* reduced {outcomes[0]}\n"
        f"→ No immediate action required; maintain baseline monitoring."
    )

    # 4. Structured Actions with explicit Priority and Rationale
    scenarios = {
        "base": {
            "text": base_text, 
            "confidence": "Medium", 
            "actions": [
                {
                    "text": f"Continue monitoring {active_domain} indicators for shift in baseline volatility.", 
                    "priority": "Monitor",
                    "rationale": f"because {outcomes[0]} persists but remains within manageable thresholds"
                }
            ]
        },
        "escalation": {
            "text": esc_text, 
            "confidence": "Low", 
            "actions": [
                {
                    "text": f"Review exposure to {outcomes[0]} and affected supply routes.", 
                    "priority": "High Priority",
                    "rationale": f"due to rising {outcomes[0]} risk in key transit nodes"
                },
                {
                    "text": f"Prepare contingency plans for sector-wide {outcomes[1]}.", 
                    "priority": "Monitor",
                    "rationale": f"as {outcomes[1]} risk in adjacent sectors is increasing"
                }
            ]
        },
        "containment": {
            "text": cont_text, 
            "confidence": "Low", 
            "actions": [
                {
                    "text": "Maintain baseline monitoring of policy signals; no immediate shift required.", 
                    "priority": "Maintain",
                    "rationale": f"as stabilization would likely reduce {outcomes[0]}"
                }
            ]
        }
    }
    
    # 5. Confidence Scaling
    if avg_score > 4.5:
        scenarios["base"]["confidence"] = "High"
        scenarios["escalation"]["confidence"] = "Medium"
        
    return scenarios
