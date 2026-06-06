import logging
import math
import re
from functools import lru_cache
from typing import List, Dict, Set, Any
from collections import Counter
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta
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

# ── Event-class lexicon (anti-"black-hole") ─────────────────────────────────────
# Distinct EVENT TYPES, used to keep semantically different stories apart even when
# they share the same geopolitical entities (e.g. a "World Cup" item and a "US/Iran
# war powers" item both name US + Iran). SOFT-news classes (sports/entertainment)
# are hard-vetoed from merging into any hard/strategic class — regardless of geo.
ACTION_LEXICON: Dict[str, tuple] = {
    "military_action": ("strike", "missile", "airstrike", "shelling", "offensive",
        "invasion", "troop", "warship", "bombard", "artillery", "siege", "combat",
        "warfare", "militant", "insurgent", "militia", "raid", "ambush", "war",
        "frontline", "casualty", "killed", "wounded", "attack", "drone", "rocket"),
    "diplomacy": ("ceasefire", "truce", "talks", "negotiation", "summit", "treaty",
        "accord", "envoy", "diplomat", "sanction", "embargo", "resolution"),
    "governance": ("election", "vote", "ballot", "parliament", "congress", "senate",
        "legislation", "bill", "war powers", "court", "ruling", "impeach",
        "cabinet", "referendum", "primary", "policy"),
    "market": ("stock", "bond", "yield", "inflation", "recession", "gdp", "earnings",
        "selloff", "rally", "index", "nasdaq", "dow", "fed", "currency", "dollar", "rate"),
    "energy": ("oil", "gas", "opec", "crude", "pipeline", "lng", "barrel", "refinery",
        "grid", "electricity"),
    "trade_supply": ("tariff", "export", "import", "shipping", "freight", "port",
        "supply chain", "container", "logistics", "cargo"),
    "crypto": ("bitcoin", "crypto", "ethereum", "stablecoin", "blockchain", "token"),
    "cyber": ("hack", "breach", "ransomware", "malware", "cyber", "phishing", "ddos", "exploit"),
    "ai_semi": ("chip", "semiconductor", "nvidia", "gpu", "llm", "data center"),
    "sports": ("world cup", "fifa", "uefa", "league", "tournament", "midfielder",
        "goalkeeper", "match", "fans", "club", "championship", "olympic", "playoff",
        "striker", "messi", "ronaldo", "super bowl", "nba", "world series", "grand slam"),
    "entertainment": ("film", "movie", "celebrity", "actor", "actress", "singer",
        "album", "hollywood", "oscar", "grammy", "netflix", "box office", "premiere",
        "concert", "sitcom", "broadcaster", "correspondent"),
}

# Soft / non-strategic event classes. A merge between a SOFT class and a non-soft
# class is hard-vetoed regardless of shared geo entities.
SOFT_CLASSES = {"sports", "entertainment"}

# Boundary-safe matchers per class (\bkw s?\b) so "war" never matches "warning"
# and "world cup" matches as a phrase. Compiled once.
_ACTION_PATTERNS = {
    cls: tuple(re.compile(r"\b" + re.escape(kw) + r"s?\b", re.IGNORECASE) for kw in kws)
    for cls, kws in ACTION_LEXICON.items()
}

# Growth backstop: required confidence rises with cluster size so a large cluster
# cannot keep absorbing loosely-related items (the "black hole" runaway).
SIZE_THRESHOLD_K = 0.05


@lru_cache(maxsize=4096)
def event_class_scores(text: str) -> tuple:
    """((class, hit_count), ...) for every event class present in text (boundary-safe)."""
    low = text or ""
    out = []
    for cls, patterns in _ACTION_PATTERNS.items():
        hits = sum(1 for p in patterns if p.search(low))
        if hits:
            out.append((cls, hits))
    return tuple(out)


def dominant_event_class(text: str):
    """The single most-represented event class in text, or None if none detected.
    Ties break by ACTION_LEXICON declaration order (stable)."""
    scores = event_class_scores(text)
    if not scores:
        return None
    return max(scores, key=lambda kv: kv[1])[0]


def _event_classes_conflict(c_a, c_b) -> bool:
    """Hard veto: exactly one side is SOFT news (sports/entertainment) → the two
    stories are categorically different events and must NEVER merge, no matter how
    many geopolitical entities they share."""
    if not c_a or not c_b or c_a == c_b:
        return False
    return (c_a in SOFT_CLASSES) != (c_b in SOFT_CLASSES)


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
    """Merge confidence, hardened against entity-only ("black hole") merges.

    Key changes vs the old Agreement-Bonus model:
    - Geo overlap is an ANCHOR, not a merge driver: it is demoted to a small weight
      and NO LONGER earns an agreement point on its own (a shared country + one
      buzzword can no longer fuse unrelated events).
    - Event-CLASS agreement (military vs market vs sports …) is a first-class
      signal; divergent hard classes are penalised.
    - The agreement bonus is shrunk from +0.30/+0.25 to +0.12/+0.10 so a real,
      multi-signal match still clears the 0.40 floor but a thin one cannot.
    """
    text1 = " ".join([i.title for i in group1])
    text2 = " ".join([i.title for i in group2])

    t1 = tokenize(text1)
    t2 = tokenize(text2)

    e1 = extract_entities(text1)
    e2 = extract_entities(text2)

    # Base similarities
    lex_sim = calculate_similarity(t1, t2)
    geo_sim = calculate_similarity(e1["geo"], e2["geo"])      # NO ×1.2 — geo demoted
    org_sim = calculate_similarity(e1["org"], e2["org"])
    sector_sim = calculate_similarity(e1["sector"], e2["sector"])

    # Event-class agreement / divergence.
    cls1 = dominant_event_class(text1)
    cls2 = dominant_event_class(text2)
    class_match = cls1 is not None and cls1 == cls2
    class_diff = cls1 is not None and cls2 is not None and cls1 != cls2

    # Agreement points — CONTENT signals only (geo is an anchor, never a point).
    match_points = 0
    if lex_sim > 0.18: match_points += 1
    if class_match: match_points += 1
    if org_sim > 0.3: match_points += 1
    if sector_sim > 0.3: match_points += 1

    # Base score: lexical core + event-class lead; geo a minor anchor.
    score = (
        (lex_sim * 0.35)
        + ((1.0 if class_match else 0.0) * 0.25)
        + (org_sim * 0.12)
        + (sector_sim * 0.10)
        + (min(geo_sim, 1.0) * 0.10)
    )

    # Shrunk agreement bonus (was +0.30 / +0.25).
    if match_points >= 2:
        score += 0.12
    if match_points >= 3:
        score += 0.10

    # Divergent hard event classes (e.g. market vs military): penalise — these are
    # different events even when they share entities.
    if class_diff and not class_match:
        score *= 0.6

    return {
        "score": min(score, 1.0),
        "details": {
            "lexical": lex_sim,
            "geo": geo_sim,
            "org": org_sim,
            "sector": sector_sim,
            "class1": cls1,
            "class2": cls2,
            "class_match": class_match,
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
# Phase 3 hardening (docs/clustering_quality_proposal.md, RC-1/RC-5): raised from
# the old 0.12-0.18 band. At those levels a single shared geo/word anchor
# (~0.26 blended) could trip a merge. A 0.40 floor means a merge now needs genuine
# MULTI-signal agreement (shared anchor AND lexical/sector overlap — the agreement
# bonus only lifts a true match to ~0.55+), so a lone buzzword can no longer fuse
# unrelated events. We prefer false negatives (separate clusters) over false
# positives (fused events) to guarantee evidence-list trust.
CATEGORY_THRESHOLDS = {
    "geopolitics": 0.40,
    "economy": 0.40,
    "cyber": 0.42,
    "supply_chain": 0.40,
    "defense": 0.40,
    "default": 0.40
}

async def cluster_items(db: Session, items: List[Item], base_threshold: float = 0.40) -> Dict:
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

        item_geo = extract_entities(item.title)["geo"]
        item_class = dominant_event_class(item.title)

        for idx, cluster in enumerate(clusters):
            # (c) FROZEN FOOTPRINT: compare against the cluster SEED (first item)
            # only — never the ever-growing concatenation of all titles. This kills
            # the "black hole" where a big cluster's expanding token/entity surface
            # keeps matching loosely-related news.
            seed = cluster[0]
            seed_geo = extract_entities(seed.title)["geo"]

            # Disjoint-geography ABSOLUTE VETO (different theaters never merge).
            if item_geo and seed_geo and not (item_geo & seed_geo):
                continue

            # (a) EVENT-CLASS ABSOLUTE VETO: soft news (sports/entertainment) vs a
            # hard/strategic event never merge, regardless of shared geo entities.
            if _event_classes_conflict(item_class, dominant_event_class(seed.title)):
                continue

            conf_data = calculate_merge_confidence([item], [seed])
            if conf_data["score"] > max_conf:
                max_conf = conf_data["score"]
                best_match_idx = idx

        # (d) SIZE-SCALED THRESHOLD: the bigger the target cluster, the higher the
        # bar to join it — a mechanical backstop against runaway absorption.
        if best_match_idx >= 0:
            size = len(clusters[best_match_idx])
            effective_threshold = threshold + SIZE_THRESHOLD_K * math.log(1 + size)
        else:
            effective_threshold = threshold

        # Multi-geo over-merge VETO: an event spanning MORE THAN 2 distinct geo
        # theaters is a macro-thread, not a single event — split it.
        if max_conf >= effective_threshold and best_match_idx >= 0:
            merged_geos: Set[str] = set()
            for it in clusters[best_match_idx]:
                merged_geos |= extract_entities(it.title)["geo"]
            merged_geos |= item_geo
            if len(merged_geos) > 2:
                clusters.append([item])
            else:
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

    # 3. Filter and Persist to DB with 2-Stage Reconciliation
    # Phase 27.2: Reconciliation Logic
    # 1. Fetch existing clusters from the last 24 hours
    limit_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    stmt_24h = select(EventCluster).where(EventCluster.created_at >= limit_24h).order_by(desc(EventCluster.created_at))
    existing_clusters = (await db.execute(stmt_24h)).scalars().all()
    
    # 2. Divide existing into 1h (Fast Path) and 24h (Deep Path)
    limit_1h = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_1h = []
    for c in existing_clusters:
        dt = c.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= limit_1h:
            recent_1h.append(c)
    
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
        
        # Reconciliation: Check if a similar cluster already exists
        matched_cluster = None
        
        rep_class = dominant_event_class(rep_item.title)

        # Stage 1: Fast Path (Last 1h)
        for ec_existing in recent_1h:
            # Event-class veto also applies on reconciliation to existing clusters.
            if _event_classes_conflict(rep_class, dominant_event_class(ec_existing.representative_title)):
                continue
            sim = calculate_similarity(tokenize(rep_item.title), tokenize(ec_existing.representative_title))
            if sim >= 0.75: # High confidence match
                matched_cluster = ec_existing
                break

        # Stage 2: Deep Path (Last 24h, skip if matched in Stage 1)
        if not matched_cluster:
            for ec_existing in existing_clusters:
                if ec_existing in recent_1h: continue # Guard
                if _event_classes_conflict(rep_class, dominant_event_class(ec_existing.representative_title)):
                    continue
                sim = calculate_similarity(tokenize(rep_item.title), tokenize(ec_existing.representative_title))
                if sim >= 0.75:
                    matched_cluster = ec_existing
                    break

        if matched_cluster:
            # Update Existing Cluster
            logger.info(f"Reconciling items to existing cluster: {matched_cluster.id} ({matched_cluster.representative_title})")
            matched_cluster.article_count += len(cluster)
            # Weighted average for score update? Simple update for now
            matched_cluster.avg_signal_score = (matched_cluster.avg_signal_score + avg_score) / 2
            
            # Update items to point to existing cluster
            for item in cluster:
                item.cluster_id = matched_cluster.id
            continue

        # Else: Create New Cluster
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
