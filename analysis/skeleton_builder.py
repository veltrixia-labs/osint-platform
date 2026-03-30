import logging
import re
from typing import List, Dict

logger = logging.getLogger(__name__)

THREADS_CTA = [
    "Read the full briefing on our platform:",
    "Full forecast and scenarios available here:",
    "Deep dive into this intelligence note:"
]

def normalize_title(title: str) -> str:
    """Normalizes news titles for professional event headlines."""
    if not title:
        return ""
    
    # 1. Remove source suffixes (- BBC, | Reuters, etc.)
    title = re.split(r' - | \| | : ', title)[0]
    
    # 2. Remove clickbait/noise prefixes
    noise_patterns = [
        r'^(Live updates|Breaking News|Exclusive|Watch|Fact Check|Opinion|Editorial): ',
        r'^VIDEO: ',
        r'^\d+ (Ways|Things|Reasons) ',
    ]
    for pattern in noise_patterns:
        title = re.sub(pattern, '', title, flags=re.IGNORECASE)
    
    # 3. Suppress Question forms / Explainers
    if title.endswith('?') or title.lower().startswith(('why ', 'how ', 'what ')):
        # Heuristic: Convert question-like header to a topical statement
        title = "Developments regarding " + title.rstrip('?')
    
    # 4. Clean quotes and extra spacing
    title = title.strip(' "\'')
    
    # 5. Length limit (110 for safety in L1)
    if len(title) > 110:
        title = title[:107].rsplit(' ', 1)[0] + "..."
        
    return title

# Risk Headline Templates (Sector-Specific)
RISK_HEADLINE_TEMPLATES = {
    "geopolitics": [
        "{theme} Risk Rises Following {event}",
        "Geopolitical Friction Builds Amid {event}",
        "{theme} Chokepoint Alerts Postured as {event}",
        "Awaiting Deployment: Naval Pressure Expands in {theme} Context"
    ],
    "cyber": [
        "{theme} Digital Vulnerability Level Shift",
        "Attribution Data Surfaces for {theme} Incidents",
        "{theme} Integrity Under Sector Pressure",
        "Surface Risk Expansion Signals {theme} Alerts"
    ],
    "economy": [
        "{theme} Liquidity Strain Indicators Rises",
        "Pricing Volatility Signal Following {event}",
        "{theme} Sensitivity Triggers Heightened Pressure",
        "Capital Pressure Expands Across {theme} Hubs"
    ],
    "market": [
        "{theme} Asset Volatility Triggers Exposure Risks",
        "Market Sensitivity Rises Following {event}",
        "{theme} Sentiment Shift Signals Amid {event}",
        "Equity Risk Exposure Expands in {theme} Context"
    ],
    "energy": [
        "Energy Security Risk Rises as {event} Expands",
        "{theme} Resource Flow Signals Monitoring Required",
        "Refinery Pressure Mounts Following {theme} Signal",
        "{theme} Output Stability Signals Under Observation"
    ],
    "defense": [
        "Defense Posture Shift Observed Amid {event}",
        "{theme} Strategic Readiness Signals Surface",
        "Procurement Friction Surface in {theme} Context",
        "{theme} Naval Deployment Risks Surface as {event}"
    ],
    "supply_chain": [
        "{theme} Bottleneck Alerts Following {event}",
        "Resource Flow Disruption as {event} Expands",
        "{theme} Constraints Signal Potential Gridlock",
        "Port Congestion Risks Mount Following {event}"
    ],
    "shared": [
        "{theme} Risk Alerts Rises Following {event}",
        "{theme} Stability Under Pressure Amid {event}",
        "{theme} Focus Required as Risk Indicators Surface",
        "Structural Friction Surface in {theme} Context"
    ]
}

WHY_IT_MATTERS_TEMPLATES = {
    "geopolitics": "Regional spillover and sanctions exposure remain elevated as geopolitical chokepoints face sustained pressure.",
    "cyber": "Critical infrastructure stability and attribution risks are intensifying following recent signal expansion.",
    "economy": "Market liquidity and pricing volatility are driving heightened policy sensitivity across global hubs.",
    "supply_chain": "Logistics bottlenecks and maritime shipping constraints threaten production stability and inventory flow.",
    "defense": "Defense procurement readiness and regional security posture shifts are signaling a transition in strategic depth.",
    "energy": "Global energy security and refinery output stability are coming under renewed pressure from supply-side risks.",
    "default": "Observed cluster activity indicates shifting risk profiles with potential for cross-sector transmission."
}

# Monitorable Watch-Points (L3)
WHAT_TO_WATCH_TEMPLATES = {
    "geopolitics": "Monitor troop movements and high-level diplomatic signaling across key corridors for escalation triggers.",
    "cyber": "Watch for attribution statements from security agencies and service status reports for infrastructure impact.",
    "economy": "Track interest rate signaling and pricing volatility in futures markets to assess cross-market sentiment.",
    "supply_chain": "Observe port congestion data and shipping insurance rates for signals of sustained delivery disruptions.",
    "defense": "Monitor procurement contracts and military exercise status for shifts in regional security readiness.",
    "energy": "Track daily output levels and storage capacity shifts to assess immediate energy resource flow risks.",
    "default": "Watch for further institutional responses and multi-source confirmation of ongoing risk trends."
}

# Domain-Specific Narrative Framing (Executive Summary)
EXECUTIVE_SUMMARY_TEMPLATES = {
    "energy": "Analysis of current energy security indicators suggests a shift in **{themes}**. The following briefing evaluates the impact on regional production and infrastructure stability.",
    "market": "Strategic intelligence regarding global market volatility indicates a convergence around **{themes}**. This report synthesizes price sensitivities and sector-wide sentiment shifts.",
    "geopolitics": "Current geopolitical indicators suggest a significant shift in **{themes}**. The following briefing assesses regional stability and the potential for strategic escalation.",
    "default": "Current intelligence indicators suggest a convergence around **{themes}**. The following briefing details the core developments and strategic implications of these shifts."
}

# State tracking for rotation (simple process-level cache)
_LAST_USED_TEMPLATE = {}
_LAST_USED_KEYWORDS = set()

def build_threads_teaser(
    top_event_title: str, 
    top_theme: str, 
    category: str, 
    target_url: str
) -> str:
    """
    Builds a 4-line authoritative Risk-focused Threads teaser.
    Evolved for Phase 14: Category-aware templates + Keyword rotation.
    """
    global _LAST_USED_TEMPLATE, _LAST_USED_KEYWORDS
    
    norm_event = normalize_title(top_event_title)
    
    # Subject Extraction (Prioritize Risk Nouns from clustering)
    from analysis.clustering import NORMALIZATION_MAP
    risk_nouns = set(NORMALIZATION_MAP.values())
    
    event_words = norm_event.lower().split()
    event_core = norm_event
    
    # Try to find a "Risk Noun" to anchor the headline
    found_risk_noun = None
    for w in event_words:
        if w in risk_nouns:
            found_risk_noun = w.capitalize()
            break
            
    if found_risk_noun and len(norm_event) > 60:
        event_core = found_risk_noun # Use the noun as the core if the title is too long
    elif ':' in norm_event:
        event_core = norm_event.split(':', 1)[1].strip()
    
    words = event_core.split()
    if len(words) > 7:
        event_core = " ".join(words[:7]) + "..."

    # Determine templates for this sector
    cat_fixed = category.lower() if category else "default"
    
    # Refined mapping for L1 (Headline)
    l1_key = "shared"
    if "energy" in cat_fixed: l1_key = "energy"
    elif "defense" in cat_fixed: l1_key = "defense"
    elif "market" in cat_fixed or "economy" in cat_fixed: l1_key = "market"
    elif "geopolitics" in cat_fixed: l1_key = "geopolitics"
    elif "cyber" in cat_fixed: l1_key = "cyber"
    elif "supply" in cat_fixed: l1_key = "supply_chain"
    
    templates = RISK_HEADLINE_TEMPLATES.get(l1_key, RISK_HEADLINE_TEMPLATES["shared"])
    
    # Rotation logic
    title_hash = hash(norm_event + top_theme)
    tpl_idx = title_hash % len(templates)
    
    # Avoid same template as last category if possible
    if _LAST_USED_TEMPLATE.get(cat_fixed) == tpl_idx:
        tpl_idx = (tpl_idx + 1) % len(templates)
    
    _LAST_USED_TEMPLATE[cat_fixed] = tpl_idx
    template = templates[tpl_idx]
    
    theme_val = top_theme or (category.capitalize() if category else "Regional")
    
    # Keyword Suppression (Avoid repeating theme in consecutive runs)
    if theme_val in _LAST_USED_KEYWORDS:
        # Subtle tweak to avoid anchor word repetition
        theme_val = f"Extended {theme_val}"
    
    _LAST_USED_KEYWORDS.add(theme_val)
    if len(_LAST_USED_KEYWORDS) > 5:
        _LAST_USED_KEYWORDS.pop() # Keep small window

    l1 = template.format(
        theme=theme_val,
        event=event_core
    )
    
    # Final cleanup
    l1 = l1.replace("  ", " ").strip()
    if len(l1) > 120:
        l1 = l1[:117] + "..."

    # Determine context key for L2/L3 (Semantic Role separation remains)
    search_text = (category or "") + " " + (top_event_title or "")
    search_text = search_text.lower()
    
    cat_key = "default"
    mapping_order = ["geopolitics", "energy", "economy", "market", "cyber", "supply_chain", "defense"]
    for k in mapping_order:
        if k in search_text:
            cat_key = k
            if k == "market": cat_key = "economy" # Shared detail templates
            break
            
    l2 = WHY_IT_MATTERS_TEMPLATES.get(cat_key, WHY_IT_MATTERS_TEMPLATES["default"])
    l3 = WHAT_TO_WATCH_TEMPLATES.get(cat_key, WHAT_TO_WATCH_TEMPLATES["default"])
    l4 = f"{THREADS_CTA[0]}\n{target_url}"
    
    return f"{l1}\n\n{l2}\n\n{l3}\n\n{l4}"

def build_substack_skeleton(
    themes: List[str], 
    developments: List[str], 
    forecasts: List[Dict], 
    scenarios: Dict, 
    sources: List[str],
    trends: Dict[str, List[str]] = None,
    visuals: List[str] = None,
    domain: str = None
) -> str:
    """
    Builds the optimized analytical skeleton report.
    Phase: Content Deduplication & Compression.
    """
    sections = []
    
    # 1. Executive Summary (Narrative Synthesis - Domain-Aware)
    narrative = ""
    domain_key = domain.lower() if domain else "default"
    if "market" in domain_key: domain_key = "market"
    if "energy" in domain_key: domain_key = "energy"
    if "geo" in domain_key: domain_key = "geopolitics"
    
    template = EXECUTIVE_SUMMARY_TEMPLATES.get(domain_key, EXECUTIVE_SUMMARY_TEMPLATES["default"])
    
    if themes:
        main_themes = ", ".join(themes[:3])
        if len(themes) > 3:
            main_themes += f", and {len(themes)-3} other emerging signals"
        narrative = template.format(themes=main_themes)
    else:
        narrative = "Analysis of current signal clusters suggests shifting risk profiles across the monitored domain. This report synthesizes key factual developments and expected impacts."
    
    sections.append("# Executive Summary\n" + narrative)

    # 1.5. Key Actions (Decision Compression)
    if scenarios:
        all_actions = []
        for case in scenarios.values():
            if "actions" in case:
                all_actions.extend(case["actions"])
        
        # Sort by Priority: High Priority (0) > Monitor (1) > Maintain (2)
        priority_map = {"High Priority": 0, "Monitor": 1, "Maintain": 2}
        all_actions.sort(key=lambda x: priority_map.get(x["priority"], 3))
        
        if all_actions:
            # Decision Compression: Max 3 actions. 
            # Ensure at least 1 High Priority if it exists.
            high_prio = [a for a in all_actions if a["priority"] == "High Priority"]
            other_prio = [a for a in all_actions if a["priority"] != "High Priority"]
            
            selected_actions = []
            if high_prio:
                selected_actions.append(high_prio[0])
                remaining = (high_prio[1:] + other_prio)
            else:
                remaining = other_prio
                
            selected_actions.extend(remaining[:3 - len(selected_actions)])
            
            action_lines = []
            for a in selected_actions:
                prio_label = a['priority']
                action_text = a['text']
                
                # Prevent "Monitor: Monitor closely"
                if action_text.lower().startswith(prio_label.lower()):
                    # Use the text as is if it already starts with the priority verb
                    line = f"- {action_text}"
                else:
                    line = f"- {prio_label}: {action_text}"
                
                if a.get('rationale'):
                    line += f" — *{a['rationale']}*"
                if a.get('confidence'):
                    line += f" — Confidence: {a['confidence']}"
                action_lines.append(line)
            
            sections.append("# Key Actions\n" + "\n".join(action_lines))
    
    # 2. Key Developments (Factual core)
    dev_str = "\n".join([f"- {d}" for d in developments[:5]])
    sections.append("# Key Developments\n" + dev_str)

    # 3. Trend Analysis (Explain pattern meaning, not just headlines)
    trend_blocks = []
    if trends:
        # High-level Risk Patterns
        if trends.get("patterns"):
            pattern_str = "Analysis of longitudinal data indicates several evolving risk patterns:\n\n"
            for p in trends["patterns"]:
                # Use "### {Pattern Name}" instead of "### Pattern: {Name}" to keep it tight
                pattern_str += f"### {p['label']} (Intensity: {p['intensity']})\n"
                pattern_str += f"{p['description']}\n"
                if p.get("supporting"):
                    # Compact view of evidence to avoid repeating Key Developments
                    pattern_str += "**Evidence Base:** " + ", ".join([ev for ev in p["supporting"][:3]]) + "\n"
                pattern_str += "\n"
            trend_blocks.append(pattern_str)

        if not trends.get("patterns"):
            if trends.get("persistent"):
                trend_blocks.append("## Longitudinal Signals\n" + "\n".join([f"- {t}" for t in trends["persistent"]]))
            if trends.get("surges"):
                trend_blocks.append("## Emerging Surges\n" + "\n".join([f"- {t}" for t in trends["surges"]]))
    
    if trend_blocks:
        visual_md = ""
        if visuals:
            for v in visuals:
                visual_md += f"![Analyst Visualization](visuals/{v})\n\n"
        sections.append("# Trend Analysis\n" + visual_md + "\n\n".join(trend_blocks))
    else:
        sections.append("# Trend Analysis\nNo significant risk patterns or surging signals detected in the current lookback window.")
    
    # 4. Impact Analysis & Watch Points (MERGED)
    impact_items = []
    for f in forecasts:
        risk = f['implication']
        # Extract watch point from existing forecast data if available, or generate a hint
        watch_hint = f.get('watch_indicator') or f"Watch for: {risk.split(' ')[0]} trigger events."
        
        # Fix Watch duplication: if it starts with "Watch for:", use as-is. Otherwise prepend "**Watch:** "
        if watch_hint.lower().startswith("watch for:"):
            watch_line = watch_hint
        else:
            watch_line = f"**Watch:** {watch_hint}"
        
        entry = f"- **{risk}**: {f['evidence']}. (Confidence: {f['confidence']})\n  {watch_line}"
        impact_items.append(entry)
    
    sections.append("# Impact Analysis & Watch Points\n" + "\n".join(impact_items))
    
    # 5. Strategic Forecast (Decision Compression Layer)
    sc_parts = []
    for label, key in [("Base Case", "base"), ("Escalation Case", "escalation"), ("Containment Case", "containment")]:
        if key in scenarios:
            s = scenarios[key]
            case_text = s['trigger'] + "\n"
            for o in s.get('outcomes', []):
                # Embedded Metadata for UI Parsing: [IMPACT: HIGH, TIME: Immediate]
                meta = f"[IMPACT: {o['impact'].replace(' IMPACT', '')}, TIME: {o['time_horizon']}]"
                case_text += f"* {o['text']} {meta}\n"
            
            if s.get('show_tension_cue'):
                case_text += "\nSignals are emerging but not yet confirmed.\n"
                
            case_text += s['action_guidance']
            sc_parts.append(f"## {label} (Confidence: {s['confidence']})\n{case_text}")
    
    if sc_parts:
        sections.append("# Strategic Forecast\n" + "\n\n".join(sc_parts))
    
    # 6. Sources
    src_str = "\n".join([f"- {s}" for s in sorted(list(set(sources)))])
    sections.append("# Sources\n" + src_str)
    
    return "\n\n".join(sections)

def validate_skeleton(content: str) -> bool:
    """Validates if the content has all 6 mandatory sections with robust parsing."""
    if not content:
        return False
        
    mandatory = [
        "Executive Summary",
        "Key Developments",
        "Trend Analysis",
        "Impact Analysis & Watch Points",
        "Strategic Forecast",
        "Sources"
    ]
    
    # 1. Check for presence of all headers
    for section in mandatory:
        header = f"# {section}"
        if header not in content:
            logger.warning(f"Skeleton validation failed: Missing section {header}")
            return False
            
    # 2. Substantiality check with explicit boundaries
    for i, section in enumerate(mandatory):
        header = f"# {section}"
        start_idx = content.find(header) + len(header)
        
        if i + 1 < len(mandatory):
            next_header = f"# {mandatory[i+1]}"
            end_idx = content.find(next_header)
        else:
            end_idx = len(content)
            
        if end_idx < start_idx:
            end_idx = len(content)
            
        body = content[start_idx:end_idx].strip()
        if len(body) < 10:
            logger.warning(f"Skeleton validation failure: Section {header} is too thin. (Len: {len(body)})")
            return False
            
    # 3. Banned Phrase Check (Phase 19.4)
    BANNED_PHRASES = ["escalating regional risks", "general escalation", "regional risk", "mixed signals"]
    content_lower = content.lower()
    for phrase in BANNED_PHRASES:
        if phrase in content_lower:
            logger.warning(f"Skeleton validation failure: Banned phrase '{phrase}' detected.")
            return False
                 
    return True
