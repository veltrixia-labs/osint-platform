def generate_scenarios(avg_score: float, forecasts: list) -> dict:
    """Generates concrete operational scenarios with structured impact/time metadata and confidence-calibrated actions."""
    
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
    
    # 3. Action Wording Helper (Decision Support Calibration)
    def calibrate_action(action_template, confidence, impact="MEDIUM"):
        # Strict Rule: Low confidence MUST NOT produce: Prepare, Reduce exposure, Execute
        if confidence == "Low":
            verbs = ["Monitor closely", "Validate signals for", "Track early indicators of"]
        elif impact == "HIGH" and confidence == "Medium":
             verbs = ["Evaluate", "Assess impact of", "Check contingency preparedness for"]
        else:
            verb_map = {
                "High": ["Review", "Prepare", "Reduce exposure to"],
                "Medium": ["Evaluate", "Monitor", "Assess impact of"],
                "Low": ["Watch for", "Validate signals regarding", "Track developments in"]
            }
            verbs = verb_map.get(confidence, verb_map["Medium"])
            
        # Simple template-based swap or prefixing
        if "{verb}" in action_template:
            v = verbs[0] if "High" not in confidence else verbs[1]
            return action_template.replace("{verb}", v)
        return f"{verbs[0]} {action_template}"

    # 3.2 Uncertainty Framing Helper (Natural Language)
    def soften_outcome(text, impact, confidence):
        # Strict Rule: If confidence is Low, soften the phrasing regardless of impact
        if confidence == "Low":
            softeners = {
                "disruptions": "potential disruptions",
                "instability": "early signs of instability",
                "pressure": "emerging pressure",
                "volatility": "potential for increased volatility",
                "gaps": "risk of supply gaps",
                "bottlenecks": "potential for bottlenecks",
                "friction": "early signs of friction",
                "exposure": "potential exposure",
                "delays": "potential delays",
                "scrutiny": "emerging scrutiny",
                "shifts": "potential shifts",
                "spikes": "potential spikes"
            }
            # Natural softening instead of mechanical prepending
            softened = False
            for word, soft in softeners.items():
                if word in text:
                    # Special case: if text is "sanctions pressure", we want "emerging sanctions pressure" 
                    # not "sanctions emerging pressure". 
                    # Strategy: If it's a domain outcome, prefix the whole thing with the softener's 'modifier' part.
                    # Or just use the keyword replacement more intelligently.
                    if word == "pressure" and "sanctions" in text:
                        return f"emerging {text}"
                    if word == "disruptions" and "supply" in text:
                        return f"potential {text}"
                    if word == "instability" and "route" in text:
                        return f"early signs of {text}"
                    
                    return text.replace(word, soft)
            
            return f"potential {text}"
        return text

    # 3.5 Scenario Construction helper
    def build_case_data(cond_trigger, outcome_indices, action_template, confidence="Low"):
        case_outcomes = []
        has_tension = False
        
        for i, idx in enumerate(outcome_indices):
            # Heuristic: First bullet is often higher impact/sooner
            impact_val = "HIGH" if (i == 0 and confidence != "Low") else "MEDIUM"
            if "escalat" in cond_trigger.lower(): impact_val = "HIGH" if i < 2 else "MEDIUM"
            
            impact_label = f"{impact_val} IMPACT"
            time = "Immediate" if i == 0 and "escalat" in cond_trigger.lower() else "Short-term"
            if i > 1: time = "Mid-term"
            
            if impact_val == "HIGH" and confidence == "Low":
                has_tension = True
            
            raw_text = outcomes[idx]
            case_outcomes.append({
                "text": soften_outcome(raw_text, impact_val, confidence),
                "impact": impact_label,
                "time_horizon": time
            })
            
        # Calibrate the single-line action guidance too
        action_guide = calibrate_action(action_template, confidence, "HIGH" if has_tension else "MEDIUM")
            
        return {
            "trigger": f"If {cond_trigger}, expect:",
            "outcomes": case_outcomes,
            "action_guidance": f"→ {action_guide}",
            "confidence": confidence,
            "show_tension_cue": has_tension
        }

    # 4. Scenario Assembly
    esc_trigger = f"escalation signals for {active_domain} increase" if "geopolitics" in active_domain else f"{active_domain} tensions escalate"
    
    # 5. Confidence Scaling (Pre-calculate for verb calibration)
    base_conf = "Medium"
    esc_conf = "Low"
    if avg_score > 4.5:
        base_conf = "High"
        esc_conf = "Medium"
    
    scenarios = {
        "base": build_case_data(
            primary_impl, [0, 1], 
            f"monitoring {active_domain} supply routes and pricing signals.",
            base_conf
        ),
        "escalation": build_case_data(
            esc_trigger, [0, 2, 3], 
            f"{outcomes[1]} and affected supply routes.",
            esc_conf
        ),
        "containment": build_case_data(
            f"stabilization measures for {active_domain} succeed", [1, 0], 
            f"Continue baseline monitoring as signals stabilize.",
            "Low"
        )
    }
    
    # Post-process containment text for stabilization
    for o in scenarios["containment"]["outcomes"]:
        o["text"] = o["text"].replace('pressure', 'stabilization').replace('volatility', 'stabilization').replace('delays', 'reduction').replace('friction', 'easing').replace('gaps', 'closure')

    # 6. Structured Actions with explicit Priority, Rationale, and Confidence Calibration
    # Base Actions
    scenarios["base"]["actions"] = [
        {
            "text": calibrate_action(f"{active_domain} indicators for shift in baseline volatility.", base_conf),
            "priority": "Monitor",
            "confidence": base_conf,
            "rationale": f"because {outcomes[0]} persists but remains within manageable thresholds"
        }
    ]
    
    # Escalation Actions (High-Tension Aware)
    esc_impact_0 = scenarios["escalation"]["outcomes"][0]["impact"].split(" ")[0]
    scenarios["escalation"]["actions"] = [
        {
            "text": calibrate_action(f"exposure to {outcomes[0]} and affected supply routes.", esc_conf, esc_impact_0),
            "priority": "High Priority",
            "confidence": esc_conf,
            "rationale": f"due to rising {outcomes[0]} risk in key transit nodes (Immediate)"
        },
        {
            "text": calibrate_action(f"contingency plans for sector-wide {outcomes[1]}.", esc_conf),
            "priority": "Monitor",
            "confidence": esc_conf,
            "rationale": f"as {outcomes[1]} risk in adjacent sectors is increasing (Short-term)"
        }
    ]
    
    scenarios["containment"]["actions"] = [
        {
            "text": "Maintain baseline monitoring of policy signals; no immediate shift required.", 
            "priority": "Maintain",
            "confidence": "Low",
            "rationale": f"as stabilization would likely reduce {outcomes[0]}"
        }
    ]
    
    return scenarios
