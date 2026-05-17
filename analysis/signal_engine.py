import logging
from typing import List, Dict
from datetime import datetime, timezone
from db.models import Item, EventCluster

logger = logging.getLogger(__name__)

# Weight configurations
AUTHORITY_WEIGHTS = {
    "bbc_world": 1.2,
    "nytimes_world": 1.3,
    "guardian_world": 1.2,
    "aljazeera_all": 1.1,
    "fed_press_all": 1.5,
    "ecb_press": 1.5,
    "oilprice_main": 1.4,
    "defensenews_rss": 1.4,
    "coindesk_rss": 1.25,
    "cointelegraph_rss": 1.2,
    "cryptoslate_feed": 1.15,
}

SEVERITY_KEYWORDS = {
    "escalation": 2.0,
    "disruption": 1.8,
    "sanction": 1.5,
    "crisis": 1.7,
    "shortage": 1.6,
    "attack": 1.9,
    "warning": 1.3,
    "unprecedented": 1.5
}

CATEGORY_PRIORITY = {
    "energy_resource_risk": 1.2,
    "global_market_intelligence": 1.1,
    "crypto_geopolitics": 1.2,
    "ai_semiconductor_intelligence": 1.15,
    "defense_technology": 1.3,
    "supply_chain_intelligence": 1.4,
}

async def calculate_cluster_signal(cluster: EventCluster, items: List[Item]) -> float:
    """Calculates a multi-factor signal score for a cluster."""
    if not items:
        return 0.0
    
    # 1. Source Authority (Average)
    source_auth = sum(AUTHORITY_WEIGHTS.get(it.source_id, 1.0) for it in items) / len(items)
    
    # 2. Recency Weight (linear decay over 7 days)
    now = datetime.now(timezone.utc)
    avg_age_hours = 0.0
    valid_items = 0
    for it in items:
        if it.published_at:
            pub_at = it.published_at
            if pub_at.tzinfo is None:
                pub_at = pub_at.replace(tzinfo=timezone.utc)
            avg_age_hours += (now - pub_at).total_seconds() / 3600
            valid_items += 1
    
    if valid_items > 0:
        avg_age_hours /= valid_items
    recency_weight = max(0.5, 2.0 - (avg_age_hours / (24 * 7)))
    
    # 3. Keyword Severity
    text_content = " ".join([it.title for it in items])
    severity_sum = 0.0
    for kw, weight in SEVERITY_KEYWORDS.items():
        if kw in text_content.lower():
            severity_sum += weight
    severity_weight = 1.0 + (min(severity_sum, 5.0) / 10.0)
    
    # 4. Multi-source Confirmation
    source_count = len(set(it.source_id for it in items))
    confirmation_bonus = min(source_count * 0.2, 1.0)
    
    # 5. Coverage Intensity
    intensity_bonus = min(len(items) * 0.1, 0.5)
    
    # 6. Category Priority
    cat_weight = CATEGORY_PRIORITY.get(cluster.category, 1.0)
    
    final_score = (source_auth * recency_weight * severity_weight * cat_weight) + confirmation_bonus + intensity_bonus
    
    # Update cluster and items
    cluster.avg_signal_score = final_score
    for it in items:
        it.lightweight_score = final_score
        
    return final_score

async def run_signal_engine(db, clusters_with_items: Dict[EventCluster, List[Item]]):
    """Orchestrates signal scoring for all clusters."""
    results = {}
    for cluster, items in clusters_with_items.items():
        score = await calculate_cluster_signal(cluster, items)
        results[cluster.id] = score
    return results
