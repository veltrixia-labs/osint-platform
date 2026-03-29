def generate_scenarios(avg_score: float, forecasts: list, domain: str = None) -> dict:
    """Generates concrete operational scenarios with standardized uncertainty qualifiers and singular actions."""
    
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
    
    # Ensure domain is normalized and handled as the primary lens
    active_domain = domain.lower() if domain else "geopolitics"
    
    # Mapping logic: If the passed domain is specialized, use its context.
    # If it's a generic one, try to refine from forecasts.
    if active_domain in ["global", "geopolitics", "market", "energy", "supply_chain", "cyber"]:
        # Standardize naming for mapping
        domain_key = active_domain
        if "market" in domain_key: domain_key = "market"
        if "energy" in domain_key: domain_key = "energy"
        if "supply" in domain_key: domain_key = "supply"
    else:
        # Fallback to inference if domain is unknown/none
        domain_key = next((d for d in domain_map if d in primary_impl), "geopolitics")
        
    outcomes = domain_map.get(domain_key, domain_map["geopolitics"])
    active_domain = domain_key
    
    # 3. Action Wording Helper (Standardized Guidance)
    def calibrate_action(template_core, confidence, impact="MEDIUM"):
        # Strict Rule: Low confidence MUST use downgraded verbs
        if confidence == "Low":
            verbs = ["Monitor closely for", "Validate signals regarding", "Track early indicators of", "Observe"]
        elif impact == "HIGH" and confidence == "Medium":
            verbs = ["Evaluate", "Assess impact of", "Check contingency preparedness for"]
        else:
            verb_map = {
                "High": ["Review", "Prepare", "Reduce exposure to"],
                "Medium": ["Evaluate", "Monitor", "Assess impact of"],
                "Low": ["Watch for", "Validate signals regarding", "Track developments in"]
            }
            verbs = verb_map.get(confidence, verb_map["Medium"])
            
        # Select exactly one verb to prevent concatenation noise
        v = verbs[0]
        # Clean the template core - remove any leading 'monitoring' or similar if they might duplicate the verb
        core = template_core.strip()
        if core.lower().startswith("monitor") or core.lower().startswith("track"):
            # If the core already has a verb-like start, just use it or adjust
            pass
            
        return f"{v} {core}"

    # 3.2 Standardized Uncertainty Framing (Strict Rule)
    def soften_outcome(text, confidence):
        # Strict Rule: If confidence is Low, use ONLY potential/early signals/possible
        if confidence == "Low":
            # Avoid "emerging" or "signs of" in outcomes
            import random
            qualifiers = ["potential", "early signals of", "possible"]
            
            # Simple keyword-based selection to make it feel natural but standardized
            if any(k in text for k in ["disruption", "instability", "spike", "volatility"]):
                q = qualifiers[1] # "early signals of"
            elif any(k in text for k in ["gap", "bottleneck", "delay"]):
                q = qualifiers[0] # "potential"
            else:
                q = qualifiers[2] # "possible"
                
            # Clean original text of any conflicting modifiers
            clean_text = text.replace("pressure", "pressure signals").replace("instability", "instability risk")
            if "potential" in clean_text or "possible" in clean_text: return clean_text
            
            return f"{q} {text}"
        return text

    # 3.5 Scenario Construction helper
    def build_case_data(cond_trigger, outcome_indices, action_template, confidence="Low"):
        # Clean Trigger Logic (Safe Patch)
        import re
        clean_text = cond_trigger.strip().rstrip('.,:;')
        
        # Strip leading systemic phrases
        for prefix in ["Expect", "Continued", "Analysis suggests"]:
            if clean_text.lower().startswith(prefix.lower()):
                clean_text = clean_text[len(prefix):].strip()
        
        # Safety Guard: If remains too verbose or messy, fallback to templates
        # (Heuristic: >80 chars or contains full-sentence punctuation/indicators)
        is_messy = len(clean_text) > 80 or "." in clean_text or clean_text.lower().startswith("no immediate")
        if is_messy:
            if "escalat" in cond_trigger.lower():
                clean_text = "escalation signals increase"
            elif "stabiliz" in cond_trigger.lower() or "succeed" in cond_trigger.lower():
                clean_text = "stabilization measures succeed"
            else:
                clean_text = "current trends persist"
                
        # Final normalization (strip leftover punctuation)
        clean_text = clean_text.lstrip().rstrip('.,:;')

        case_outcomes = []
        has_tension = False
        
        for i, idx in enumerate(outcome_indices):
            # Heuristic: First bullet is often higher impact
            impact_val = "HIGH" if (i == 0 and confidence != "Low") else "MEDIUM"
            if "escalat" in cond_trigger.lower(): impact_val = "HIGH" if i < 2 else "MEDIUM"
            
            impact_label = f"{impact_val} IMPACT"
            time = "Immediate" if i == 0 and "escalat" in cond_trigger.lower() else "Short-term"
            if i > 1: time = "Mid-term"
            
            if impact_val == "HIGH" and confidence == "Low":
                has_tension = True
            
            raw_text = outcomes[idx]
            case_outcomes.append({
                "text": soften_outcome(raw_text, confidence),
                "impact": impact_label,
                "time_horizon": time
            })
            
        # Refactored: calibrate_action returns exactly ONE sentence
        action_sentence = calibrate_action(action_template, confidence, "HIGH" if has_tension else "MEDIUM")
            
        return {
            "trigger": f"If {clean_text}, expect:",
            "outcomes": case_outcomes,
            "action_guidance": f"→ {action_sentence}",
            "confidence": confidence,
            "show_tension_cue": has_tension
        }

    # 4. Scenario Assembly
    esc_trigger = f"escalation signals for {active_domain} increase" if "geopolitics" in active_domain else f"{active_domain} tensions escalate"
    
    # 5. Confidence Scaling
    base_conf = "Medium"
    esc_conf = "Low"
    if avg_score > 4.5:
        base_conf = "High"
        esc_conf = "Medium"
    
    scenarios = {
        "base": build_case_data(
            primary_impl, [0, 1], 
            f"{active_domain} supply routes and pricing signals.",
            base_conf
        ),
        "escalation": build_case_data(
            esc_trigger, [0, 2, 3], 
            f"{outcomes[1]} and affected supply routes.",
            esc_conf
        ),
        "containment": build_case_data(
            f"stabilization measures for {active_domain} succeed", [1, 0], 
            f"baseline monitoring as signals stabilize.",
            "Low"
        )
    }
    
    # Post-process containment text for stabilization
    for o in scenarios["containment"]["outcomes"]:
        o["text"] = o["text"].replace('pressure', 'stabilization').replace('volatility', 'stabilization').replace('delays', 'reduction').replace('friction', 'easing').replace('gaps', 'closure')

    # 6. Structured Actions (Single-Sentence Calibration)
    scenarios["base"]["actions"] = [
        {
            "text": calibrate_action(f"{active_domain} indicators for shift in baseline volatility.", base_conf),
            "priority": "Monitor",
            "confidence": base_conf,
            "rationale": f"because {outcomes[0]} persists but remains within manageable thresholds"
        }
    ]
    
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
