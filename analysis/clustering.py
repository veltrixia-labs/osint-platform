import logging
import re
from typing import List, Dict, Set, Any
from collections import Counter
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from db.models import Item, EventCluster
import uuid

logger = logging.getLogger(__name__)

# Normalization Map for OSINT/Risk Terms
NORMALIZATION_MAP = {
    "sanctions": "sanction",
    "deployments": "deployment",
    "deployment": "deployment",
    "exports": "export",
    "bottlenecks": "bottleneck",
    "attacks": "attack",
    "shippings": "shipping",
    "tensions": "tension",
    "tariffs": "tariff",
    "restrictions": "restriction",
    "disruptions": "disruption",
    "chinas": "china",
    "iranian": "iran",
    "irans": "iran",
    "russian": "russia",
    "russias": "russia",
    "israeli": "israel",
    "israels": "israel",
    "chinese": "china",
    "american": "usa",
    "us": "usa",
    "u.s.": "usa"
}

# Sector Entity Markers
SECTOR_ENTITIES = {
    "energy", "shipping", "semiconductor", "banking", "telecom", "defense", 
    "mining", "resource", "logistics", "commodity", "oil", "gas", "chips", 
    "cyber", "security", "financial", "trading", "supply", "vulnerability"
}

# Geopolitical Entity Markers (Common Anchor Points)
GEO_ENTITIES = {
    "hormuz", "taiwan", "ukraine", "russia", "china", "iran", "israel", "gaza",
    "usa", "arctic", "baltic", "red sea", "suez", "middle east", "beijing",
    "tehran", "moscow", "washington", "london", "kyiv", "lebanon", "syria",
    "yemen", "houthi", "nato", "eu", "un", "asean", "brics"
}

def normalize_word(word: str) -> str:
    word = word.lower()
    return NORMALIZATION_MAP.get(word, word)

def extract_entities(text: str) -> Dict[str, Set[str]]:
    """Simple rule-based classification of entities."""
    # Pre-clean: Replace apostrophes with space to prevent "China's" -> "Chinas"
    clean_text = text.lower().replace("'s", " ").replace("’s", " ")
    clean_text = re.sub(r'[^\w\s]', ' ', clean_text)
    tokens = clean_text.split()
    
    entities = {
        "geo": set(),
        "org": set(),
        "sector": set(),
        "other_proper": set()
    }
    
    # Check fixed lists
    for token in tokens:
        if token in GEO_ENTITIES:
            entities["geo"].add(token)
        if token in SECTOR_ENTITIES:
            entities["sector"].add(token)
            
    # Heuristic for orgs (capitalized but not in geo/sector)
    raw_words = text.split()
    for idx, word in enumerate(raw_words):
        clean = word.strip('.,:;"\'').lower()
        if not clean: continue
        
        # Proper noun heuristic: Capitalized, not at start, or followed by capitalized
        # Exclude common start words and stop words
        if word[0].isupper() and clean not in GEO_ENTITIES and clean not in ["a", "the", "in", "on", "at", "to", "for", "with", "by"]:
            if idx > 0 or (idx < len(raw_words)-1 and raw_words[idx+1][0].isupper()):
                entities["org"].add(clean)
            
    return entities

def calculate_merge_confidence(group1: List[Item], group2: List[Item]) -> Dict[str, float]:
    """Calculates merge confidence with Agreement Bonus logic (Phase 16)."""
    text1 = " ".join([i.title for i in group1])
    text2 = " ".join([i.title for i in group2])
    
    t1 = tokenize(text1)
    t2 = tokenize(text2)
    
    e1 = extract_entities(text1)
    e2 = extract_entities(text2)
    
    # Base similarities
    lex_sim = calculate_similarity(t1, t2)
    geo_sim = calculate_similarity(e1["geo"], e2["geo"])
    org_sim = calculate_similarity(e1["org"], e2["org"])
    sector_sim = calculate_similarity(e1["sector"], e2["sector"])
    
    # Agreement Bonus Logic:
    # We want to reward the PRESENCE of multiple matching signals.
    match_points = 0
    if lex_sim > 0.15: match_points += 1
    if geo_sim > 0.5: match_points += 1 # Over 50% of geo entities match
    if org_sim > 0.3: match_points += 1
    if sector_sim > 0.3: match_points += 1
    
    # Base score (Lower weights to avoid single-factor merge)
    score = (lex_sim * 0.2) + (geo_sim * 0.2) + (org_sim * 0.15) + (sector_sim * 0.15)
    
    # Agreement Bonus
    if match_points >= 2:
        score += 0.25
    if match_points >= 3:
        score += 0.2
        
    return {
        "score": min(score, 1.0),
        "details": {
            "lexical": lex_sim,
            "geo": geo_sim,
            "org": org_sim,
            "sector": sector_sim,
            "match_points": match_points
        }
    }

def tokenize(text: str) -> Set[str]:
    """Simple tokenizer for rule-based clustering."""
    if not text:
        return set()
    # Remove apostrophes specifically before general punctuation
    text = text.lower().replace("'s", " ").replace("’s", " ")
    text = re.sub(r'[^\w\s]', ' ', text)
    return set(text.split())

def calculate_similarity(tokens1: Set[str], tokens2: Set[str]) -> float:
    """Jaccard similarity between two sets of tokens."""
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)

# Category Threshold Mapping
CATEGORY_THRESHOLDS = {
    "geopolitics": 0.15,
    "economy": 0.18,
    "cyber": 0.22,
    "supply_chain": 0.15,
    "defense": 0.15,
    "default": 0.18
}

async def cluster_items(db: Session, items: List[Item], base_threshold: float = 0.18) -> Dict:
    """
    Groups items with Phase 16 Intelligence Evolution logic.
    - Agreement Bonus logic
    - Category-specific thresholds
    - Refined split detection
    """
    if not items:
        return {"clusters_created": 0}

    # 1. Clustering logic
    clusters: List[List[Item]] = []
    
    for item in items:
        best_match_idx = -1
        max_conf = 0.0
        
        # Determine category-specific threshold
        item_cat = (item.category or item.rough_category or "default").lower()
        threshold = CATEGORY_THRESHOLDS.get(item_cat, base_threshold)
        
        for idx, cluster in enumerate(clusters):
            conf_data = calculate_merge_confidence([item], cluster)
            
            # Safeguard: Hard Location Conflict
            e_item = extract_entities(item.title)
            e_cluster = extract_entities(" ".join([it.title for it in cluster]))
            if e_item["geo"] and e_cluster["geo"] and not (e_item["geo"] & e_cluster["geo"]):
                conf_data["score"] *= 0.1 # Severe penalty for location mismatch
                
            if conf_data["score"] > max_conf:
                max_conf = conf_data["score"]
                best_match_idx = idx
        
        if max_conf >= threshold:
            clusters[best_match_idx].append(item)
        else:
            clusters.append([item])
            
    # 2. Metrics & Quality Validation
    metrics = {
        "clusters_created": len(clusters),
        "total_items": len(items),
        "avg_items_per_cluster": len(items) / len(clusters) if clusters else 0,
        "max_items_per_cluster": max([len(c) for c in clusters]) if clusters else 0,
        "singleton_cluster_count": len([c for c in clusters if len(c) == 1]),
        "possible_overmerged_cluster_count": 0,
        "possible_split_cluster_count": 0,
        "cluster_confidence_avg": 0.0
    }
    
    conf_sum = 0.0
    for i, cluster in enumerate(clusters):
        if len(cluster) > 1:
            # Check for conflicting Geos to flag over-merge
            geos = set()
            for it in cluster:
                geos.update(extract_entities(it.title)["geo"])
            if len(geos) > 2: # More than 2 distinct locations in one cluster is suspicious
                metrics["possible_overmerged_cluster_count"] += 1
                
            # Average confidence
            item_confs = []
            for j in range(1, len(cluster)):
                item_confs.append(calculate_merge_confidence([cluster[0]], [cluster[j]])["score"])
            conf_sum += sum(item_confs) / len(item_confs)
            
        # Check for split clusters
        for j, other_cluster in enumerate(clusters):
            if i >= j: continue
            split_conf = calculate_merge_confidence(cluster, other_cluster)["score"]
            if split_conf > 0.25: # Using a more robust split threshold
                metrics["possible_split_cluster_count"] += 1

    metrics["cluster_confidence_avg"] = conf_sum / len([c for c in clusters if len(c) > 1]) if any(len(c) > 1 for c in clusters) else 0

    # 3. Filter and Persist to DB
    # Phase 27: Emergency Write Reduction
    # - Only keep clusters with at least 2 articles (reduces noise/volume)
    # - Hard cap at Top 50 clusters by avg_signal_score per run
    
    valid_clusters = []
    for cluster in clusters:
        if len(cluster) >= 2:
            avg_score = sum(it.lightweight_score for it in cluster) / len(cluster)
            valid_clusters.append((avg_score, cluster))
            
    # Sort and Cap
    valid_clusters.sort(key=lambda x: x[0], reverse=True)
    top_clusters = valid_clusters[:50]
    
    for avg_score, cluster in top_clusters:
        rep_item = cluster[0]
        # ... (rest of the persistence logic stays same, using avg_score)
        
        # 3.1 Calculate Temporal Span
        publish_times = []
        for it in cluster:
            if it.published_at:
                dt = it.published_at
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                publish_times.append(dt)
        
        now_aware = datetime.now(timezone.utc)
        first_seen = min(publish_times) if publish_times else now_aware
        last_seen = max(publish_times) if publish_times else now_aware
        time_span_hours = (last_seen - first_seen).total_seconds() / 3600 if publish_times else 0
        
        # 3.2 Calculate Entity Frequency
        all_geos = []
        all_orgs = []
        for it in cluster:
            e = extract_entities(it.title)
            all_geos.extend(list(e["geo"]))
            all_orgs.extend(list(e["org"]))
        
        top_geos = [item for item, count in Counter(all_geos).most_common(5)]
        top_orgs = [item for item, count in Counter(all_orgs).most_common(5)]
        
        # 3.3 Diversity Metrics
        source_count = len(set(it.source_name for it in cluster))
        diversity_score = source_count / len(cluster) if cluster else 0
        
        ec = EventCluster(
            id=uuid.uuid4(),
            representative_title=rep_item.title,
            category=rep_item.category or rep_item.rough_category,
            article_count=len(cluster),
            source_count=source_count,
            avg_signal_score=avg_score,
            metrics_json={
                "cluster_size": len(cluster),
                "source_diversity": round(diversity_score, 2),
                "time_span_hours": round(time_span_hours, 1),
                "purity_hint": "top_n_cap_v27"
            },
            summary_data={
                "keywords": list(tokenize(rep_item.title))[:10],
                "top_geos": top_geos,
                "top_orgs": top_orgs,
                "first_seen_at": first_seen.isoformat(),
                "last_seen_at": last_seen.isoformat()
            }
        )
        db.add(ec)
        for item in cluster:
            item.cluster_id = ec.id
            
    await db.commit()
    logger.info(f"Clustering complete: {metrics}. Persisted {len(top_clusters)} clusters.")
    return metrics
    logger.info(f"Clustering complete: {metrics}")
    return metrics
