import collections
import re
from typing import List, Dict

# OSINT/News Specific Stopwords
OSINT_STOPWORDS = {
    "says", "said", "warns", "warned", "amid", "after", "before", "over", "under",
    "new", "latest", "live", "update", "report", "reports", "breaking", "exclusive",
    "watch", "updates", "briefing", "daily", "summary", "analysis", "coverage"
}

# Geopolitical/Sector weights
KNOWN_ENTITIES = {
    "hormuz", "taiwan", "ukraine", "russia", "china", "iran", "israel", "gaza",
    "nato", "opec", "fed", "ecb", "semiconductor", "sanctions", "tariff", "chokepoint",
    "maritime", "energy", "resource", "escalation", "conflict", "cyber", "ai"
}

# Import normalization from clustering if possible, else redefine
from analysis.clustering import normalize_word

def extract_themes(items: List, top_n: int = 2) -> List[str]:
    """Extracts major intelligence themes as analyst phrases."""
    if not items:
        return ["Neutral Monitoring"]
        
    geo_weights = collections.Counter()
    sector_weights = collections.Counter()
    risk_weights = collections.Counter()
    
    for item in items:
        # Cluster signal multiplier
        weight = getattr(item, 'lightweight_score', 1.0)
        title = (item.title or "").lower()
        
        # Clean apostrophes
        title = title.replace("'s", " ").replace("’s", " ")
        words = re.sub(r'[^\w\s]', ' ', title).split()
        
        for word in words:
            clean = normalize_word(word)
            if len(clean) <= 3 or clean in OSINT_STOPWORDS:
                continue
            
            # Use clustering markers to categorize
            from analysis.clustering import GEO_ENTITIES, SECTOR_ENTITIES
            if clean in GEO_ENTITIES:
                geo_weights[clean.capitalize()] += weight * 2.0
            elif clean in SECTOR_ENTITIES:
                sector_weights[clean.capitalize()] += weight * 1.5
            else:
                risk_weights[clean.capitalize()] += weight
    
    # Build Analyst Phrases
    top_geos = [w for w, _ in geo_weights.most_common(2)]
    top_sectors = [w for w, _ in sector_weights.most_common(2)]
    top_risks = [w for w, _ in risk_weights.most_common(2)]
    
    phrases = []
    if top_geos and top_sectors:
        phrases.append(f"{top_geos[0]} {top_sectors[0].lower()} infrastructure risk")
    elif top_geos and top_risks:
        phrases.append(f"{top_geos[0]} {top_risks[0].lower()} escalation")
    elif top_sectors and top_risks:
        phrases.append(f"{top_sectors[0]} {top_risks[0].lower()} tension")
    
    # Fallback to single words or hardcoded defaults if phrases couldn't be built
    if not phrases:
        fallback_words = [w for w, _ in (geo_weights + sector_weights + risk_weights).most_common(3)]
        phrases = [w for w in fallback_words if len(w) > 2] # Be a bit more lenient in fallback
        
    if not phrases:
        phrases = ["Strategic Monitoring"]
        
    return phrases[:top_n]

def build_narrative_summary(themes: List[str], cluster_count: int) -> str:
    """Builds a professional intelligence narrative from themes."""
    if not themes:
        return "Coverage is currently monitoring baseline regional and sector trends."
    
    if len(themes) >= 3:
        theme_str = f"{themes[0]}, {themes[1]}, and {themes[2]}"
    elif len(themes) == 2:
        theme_str = f"{themes[0]} and {themes[1]}"
    else:
        theme_str = themes[0]
        
    templates = [
        f"Intelligence coverage is currently concentrating around {theme_str} across {cluster_count} event clusters.",
        f"Recent cluster activity indicates heightened analytical focus on {theme_str}.",
        f"Current reporting points to elevated attention on {theme_str} and related risk transmission."
    ]
    # Simple rotation based on cluster count for variety
    return templates[cluster_count % len(templates)]
