def generate_scenarios(avg_score: float, forecasts: list) -> dict:
    """Generates concrete operational scenarios with structured impact/time metadata."""
    
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
    
    # 3. Scenario Construction helper
    def build_case_data(cond_trigger, outcome_indices, action_guide, confidence="Low"):
        case_outcomes = []
        for i, idx in enumerate(outcome_indices):
            # Heuristic: First bullet is often higher impact/sooner
            impact = "HIGH IMPACT" if i == 0 and confidence != "Low" else "MEDIUM IMPACT"
            if "escalat" in cond_trigger.lower(): impact = "HIGH IMPACT" if i < 2 else "MEDIUM IMPACT"
            
            time = "Immediate" if i == 0 and "escalat" in cond_trigger.lower() else "Short-term"
            if i > 1: time = "Mid-term"
            
            case_outcomes.append({
                "text": outcomes[idx],
                "impact": impact,
                "time_horizon": time
            })
            
        return {
            "trigger": f"If {cond_trigger}, expect:",
            "outcomes": case_outcomes,
            "action_guidance": action_guide,
            "confidence": confidence
        }

    # 4. Scenario Assembly
    esc_trigger = f"escalation signals for {active_domain} increase" if "geopolitics" in active_domain else f"{active_domain} tensions escalate"
    
    scenarios = {
        "base": build_case_data(
            primary_impl, [0, 1], 
            f"→ Continue monitoring {active_domain} supply routes and pricing signals.",
            "Medium"
        ),
        "escalation": build_case_data(
            esc_trigger, [0, 2, 3], 
            f"→ Prepare for short-term {outcomes[1]} and review exposure.",
            "Low"
        ),
        "containment": build_case_data(
            f"stabilization measures for {active_domain} succeed", [1, 0], 
            f"→ No immediate action required; maintain baseline monitoring.",
            "Low"
        )
    }
    
    # Post-process containment text for stabilization
    for o in scenarios["containment"]["outcomes"]:
        o["text"] = o["text"].replace('pressure', 'stabilization').replace('volatility', 'stabilization').replace('delays', 'reduction').replace('friction', 'easing').replace('gaps', 'closure')

    # 5. Structured Actions with explicit Priority and Rationale (Linked to signals)
    scenarios["base"]["actions"] = [
        {
            "text": f"Continue monitoring {active_domain} indicators for shift in baseline volatility.", 
            "priority": "Monitor",
            "rationale": f"because {outcomes[0]} persists but remains within manageable thresholds"
        }
    ]
    
    scenarios["escalation"]["actions"] = [
        {
            "text": f"Review exposure to {outcomes[0]} and affected supply routes.", 
            "priority": "High Priority",
            "rationale": f"due to rising {outcomes[0]} risk in key transit nodes (Immediate)"
        },
        {
            "text": f"Prepare contingency plans for sector-wide {outcomes[1]}.", 
            "priority": "Monitor",
            "rationale": f"as {outcomes[1]} risk in adjacent sectors is increasing (Short-term)"
        }
    ]
    
    scenarios["containment"]["actions"] = [
        {
            "text": "Maintain baseline monitoring of policy signals; no immediate shift required.", 
            "priority": "Maintain",
            "rationale": f"as stabilization would likely reduce {outcomes[0]}"
        }
    ]
    
    # 6. Confidence Scaling
    if avg_score > 4.5:
        scenarios["base"]["confidence"] = "High"
        scenarios["escalation"]["confidence"] = "Medium"
        
    return scenarios
