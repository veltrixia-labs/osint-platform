import logging
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from db.models import EventCluster, TrendSignal, Item
from analysis.clustering import NORMALIZATION_MAP, extract_entities

logger = logging.getLogger(__name__)

# Config
TREND_LOOKBACK_DAYS = 7
SURGE_THRESHOLD = 1.5 # 150% of baseline

def _ensure_utc(dt: datetime) -> datetime:
    if dt is None: return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

async def detect_trends(db: AsyncSession):
    """Main entry point for trend detection."""
    logger.info("Starting Trend Detection Engine")
    
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=TREND_LOOKBACK_DAYS)
    recent_start = now - timedelta(hours=24)
    
    # 1. Fetch historical clusters
    stmt = select(EventCluster).where(EventCluster.created_at >= window_start)
    all_clusters = (await db.execute(stmt)).scalars().all()
    
    if not all_clusters:
        logger.info("No clusters found for trend analysis.")
        return
    
    recent_clusters = [c for c in all_clusters if _ensure_utc(c.created_at) >= recent_start]
    historical_clusters = [c for c in all_clusters if _ensure_utc(c.created_at) < recent_start]
    
    # 2. Collect Raw Signals (Tracked by cluster_id if applicable)
    # key: cluster_id or normalized target_label, value: TrendSignal
    signal_map = {}

    def normalize_label(l: str) -> str:
        if not l: return ""
        import re
        l = l.lower().strip()
        l = re.sub(r'\s+', ' ', l)
        return l.rstrip('.!?:;,')

    def add_signal(sig: TrendSignal, cluster_id: str = None):
        # Refined Merge Key: cluster_id takes priority
        n_label = normalize_label(sig.target_label)
        key = cluster_id if cluster_id else f"label:{n_label}"
        
        if key in signal_map:
            existing = signal_map[key]
            logger.info(f"[Trend Engine] ENFORCED MERGE: key={key} type='{existing.trend_type}' + '{sig.trend_type}'")
            # 1. Merge semantics
            if existing.trend_type != sig.trend_type and "_merged" not in existing.trend_type:
                existing.trend_type = f"{existing.trend_type}_merged"
            
            # 2. Maximize intensity
            if sig.intensity_score > existing.intensity_score:
                existing.intensity_score = sig.intensity_score
            
            # 3. Prefer most informative description (longest clean description)
            if len(sig.description or "") > len(existing.description or ""):
                existing.description = sig.description
            
            # 4. Consolidate metadata
            orig_types = existing.metrics_json.get("original_types", [existing.trend_type.split('_')[0]])
            if sig.trend_type not in orig_types:
                orig_types.append(sig.trend_type)
            
            existing.metrics_json.update(sig.metrics_json)
            existing.metrics_json["original_types"] = orig_types
            existing.metrics_json["is_merged"] = True
            if cluster_id:
                existing.metrics_json["cluster_id"] = cluster_id
        else:
            signal_map[key] = sig

    # Run detectors
    # Detectors return (TrendSignal, cluster_id_or_none)
    for sig, cid in await _detect_entity_heat(recent_clusters, historical_clusters, window_start, now):
        add_signal(sig, cid)
    for sig, cid in await _detect_sector_surges(recent_clusters, historical_clusters, window_start, now):
        add_signal(sig, cid)
    for sig, cid in await _detect_sustained_events(recent_clusters, historical_clusters, window_start, now):
        add_signal(sig, cid)
    for sig, cid in await _detect_risk_acceleration(recent_clusters, historical_clusters, window_start, now):
        add_signal(sig, cid)
    
    raw_signals = list(signal_map.values())

    # 3. Compression Layer (Phase 19.3)
    compressed_patterns = _compress_trends(raw_signals, window_start, now, is_global=True)
    
    # 4. Save to DB with Duplicate Guard
    # Check what already exists in the latest window to avoid duplicates across runs
    logger.info(f"Applying Insertion Guard for {len(raw_signals) + len(compressed_patterns)} signals...")
    
    # Pre-fetch recent signals to avoid N+1 queries
    stmt = select(TrendSignal).where(TrendSignal.created_at >= recent_start)
    db_recent_signals = (await db.execute(stmt)).scalars().all()
    
    # Map for quick lookup: (type, target_label, cluster_id) -> TrendSignal
    def get_guard_key(s: TrendSignal) -> tuple:
        cid = s.metrics_json.get("cluster_id") if s.metrics_json else None
        # Normalize label for matching
        import re
        l = (s.target_label or "").lower().strip()
        l = re.sub(r'\s+', ' ', l).rstrip('.!?:;,')
        return (s.trend_type, l, str(cid) if cid else None)

    guard_map = {get_guard_key(s): s for s in db_recent_signals}
    
    created_count = 0
    merged_count = 0
    
    for sig in raw_signals + compressed_patterns:
        key = get_guard_key(sig)
        if key in guard_map:
            existing = guard_map[key]
            # MERGE LOGIC (Root Fix #3)
            # 1. Keep max intensity
            if sig.intensity_score > existing.intensity_score:
                existing.intensity_score = sig.intensity_score
            
            # 2. Update description if longer
            if len(sig.description or "") > len(existing.description or ""):
                existing.description = sig.description
                
            # 3. Update metrics
            if sig.metrics_json:
                existing.metrics_json.update(sig.metrics_json)
                
            merged_count += 1
        else:
            db.add(sig)
            created_count += 1
    
    logger.info(f"Trend Detection Engine finished. Created {created_count} new, merged {merged_count} into existing.")

def _compress_trends(signals: List[TrendSignal], start: datetime, end: datetime, is_global: bool = True) -> List[TrendSignal]:
    """Compresses individual signals into semantic analyst-driven risk patterns."""
    if not signals:
        return []

    # 0. Risk Filter: Exclude non-risk news if global (e.g., F1, general business news without risk)
    RISK_STOPWORDS = {"f1", "grandprix", "entertainment", "sports", "celebrity", "lifestyle"}
    filtered_signals = []
    for s in signals:
        if is_global:
            content_lower = (s.target_label + " " + s.description).lower()
            if any(stop in content_lower for stop in RISK_STOPWORDS):
                continue
        filtered_signals.append(s)
    
    if not filtered_signals:
        return []

    # 1. Enrich signals with semantic features
    enriched = []
    for s in filtered_signals:
        features = extract_entities(s.target_label + " " + s.description)
        # Identify "Risk nouns" from normalized description
        words = s.description.lower().split()
        risk_nouns = set([NORMALIZATION_MAP.get(w, w) for w in words if NORMALIZATION_MAP.get(w, w) in ["disruption", "escalation", "attack", "sanction", "bottleneck", "tension", "tariff", "conflict", "instability"]])
        
        enriched.append({
            "signal": s,
            "geo": features["geo"],
            "sector": features["sector"],
            "risk_nouns": risk_nouns,
            "entities": features["org"]
        })

    # 2. Semantic Grouping Logic (Strictly Semantic)
    groups = []
    for item in enriched:
        best_group_idx = -1
        max_overlap = 0
        
        for idx, group in enumerate(groups):
            # Calculate overlap score
            geo_overlap_set = item["geo"] & group["geo"]
            sector_overlap_set = item["sector"] & group["sector"]
            risk_overlap_set = item["risk_nouns"] & group["risk_nouns"]
            entity_overlap_set = item["entities"] & group["entities"]
            
            geo_match = len(geo_overlap_set)
            sector_match = len(sector_overlap_set)
            risk_match = len(risk_overlap_set)
            entity_match = len(entity_overlap_set)
            
            # Score Calculation (Phase 19.4 Weighted)
            overlap = (geo_match * 4) + (risk_match * 3) + (sector_match * 2) + (entity_match * 1)
            
            if overlap >= 6: # High-Cohesion Threshold (Phase 19.4 Final)
                logger.debug(f"[Trend Grouping] Merging '{item['signal'].target_label}' into group '{list(group['geo'])[0] if group['geo'] else 'None'}' "
                             f"Score: {overlap} (Geo:{geo_match}, Risk:{risk_match}, Sector:{sector_match}, Ent:{entity_match}) "
                             f"Overlaps: {geo_overlap_set | risk_overlap_set | sector_overlap_set | entity_overlap_set}")
                             
            if overlap > max_overlap and overlap >= 6: 
                max_overlap = overlap
                best_group_idx = idx
                
        if best_group_idx >= 0:
            groups[best_group_idx]["items"].append(item)
            groups[best_group_idx]["geo"] |= item["geo"]
            groups[best_group_idx]["sector"] |= item["sector"]
            groups[best_group_idx]["risk_nouns"] |= item["risk_nouns"]
            groups[best_group_idx]["entities"] |= item["entities"]
        else:
            # Only create group if it has semantic anchors (Geo or Sector or Entity)
            if item["geo"] or item["sector"] or item["entities"]:
                groups.append({
                    "items": [item],
                    "geo": set(item["geo"]),
                    "sector": set(item["sector"]),
                    "risk_nouns": set(item["risk_nouns"]),
                    "entities": set(item["entities"])
                })

    # 3. Create Structured Risk Patterns
    for g in groups:
        total_intensity = sum(i["signal"].intensity_score for i in g["items"])
        diversity_bonus = 1 + (0.15 * len(set([i["signal"].trend_type for i in g["items"]])))
        g["combined_score"] = total_intensity * diversity_bonus

    groups.sort(key=lambda x: x["combined_score"], reverse=True)
    top_3 = groups[:3] # Hard cap 3 patterns
    
    if not top_3:
        return []

    # Normalization scale (Target max is 10.0)
    top_score = top_3[0]["combined_score"] if top_3 else 1.0
    scale = 10.0 / top_score if top_score > 0 else 1.0

    patterns = []
    CONTROLLED_TERMS = ["strategic", "infrastructure", "market", "security", "energy"]
    BANNED_PHRASES = ["escalating regional risks", "general escalation", "regional risk", "mixed signals"]

    for g in top_3:
        # 4. Generate Analyst Phrase for Target Label (Refined Phase 19.4)
        geos = sorted(list(g["geo"]))
        sectors = sorted(list(g["sector"]))
        risks = sorted(list(g["risk_nouns"]))
        entities = sorted(list(g["entities"]))
        
        # Semantic Label Construction (Strict Triplets)
        label = ""
        if geos and sectors and risks:
            label = f"{geos[0].capitalize()} {sectors[0]} {risks[0]}"
        elif geos and sectors:
            label = f"{geos[0].capitalize()} {sectors[0]} risk"
        elif geos and risks:
            label = f"{geos[0].capitalize()} {risks[0]} escalation"
        elif entities and risks:
            label = f"{entities[0].capitalize()} {risks[0]}"
        
        # Safety Fallback: Use controlled vocabulary if fragmented or banned
        if not label or label.lower() in BANNED_PHRASES:
            main_geo = geos[0].capitalize() if geos else "Global"
            main_sector = sectors[0].lower() if sectors else (entities[0].lower() if entities else "strategic")
            # Map main_sector to controlled vocabulary if possible
            controlled = next((t for t in CONTROLLED_TERMS if t in main_sector), "strategic")
            label = f"{main_geo} {controlled} risk"
            
        label = label.replace("  ", " ").strip()
            
        # 5. Weighted Relevance Scoring for Supporting Events (Phase 19.4)
        # Weights: Geo(4) > Risk(3) > Sector(2) > Entity(1)
        scored_events = []
        for i in g["items"]:
            sig = i["signal"]
            # Calculate Semantic Relevance components
            geo_overlap = len(i["geo"] & g["geo"])
            risk_overlap = len(i["risk_nouns"] & g["risk_nouns"])
            sector_overlap = len(i["sector"] & g["sector"])
            entity_overlap = len(i["entities"] & g["entities"])
            
            relevance = (geo_overlap * 4) + (risk_overlap * 3) + (sector_overlap * 2) + (entity_overlap * 1)
            # Blended Score: 40% Intensity, 60% Semantic Relevance
            blended_score = (sig.intensity_score * 0.4) + (relevance * 0.6)
            
            # STRICT REJECTION: If relevance is 0, reject even if intensity is high
            if relevance > 0:
                scored_events.append((sig.target_label, blended_score))
            
        # Deduplicate and sort by blended score
        sorted_events = sorted(scored_events, key=lambda x: x[1], reverse=True)
        unique_supporting = []
        seen_titles = set()
        for title, score in sorted_events:
            if title not in seen_titles:
                unique_supporting.append(title)
                seen_titles.add(title)
            if len(unique_supporting) >= 3:
                break
        
        description = f"Semantic risk pattern identified around {label}. "
        description += f"Supported by {len(g['items'])} correlated developments across {len(geos) if geos else 1} geographical nodes."
        
        # 6. Strict 0-10 Clamping
        final_score = round(min(max(float(g["combined_score"] * scale), 0.1), 10.0), 1)
        
        metrics = {
            "baseline": round(sum(i["signal"].metrics_json.get("baseline", 0) for i in g["items"]) / len(g["items"]), 2),
            "recent": round(sum(i["signal"].metrics_json.get("recent", 0) for i in g["items"]) / len(g["items"]), 2),
            "delta": round(sum(i["signal"].metrics_json.get("delta", 0) for i in g["items"]) / len(g["items"]), 2),
            "supporting_events": unique_supporting,
            "supporting_events_count": len(unique_supporting),
            "supporting_cluster_count": int(sum(i["signal"].metrics_json.get("supporting_cluster_count", 0) for i in g["items"]))
        }
        
        patterns.append(TrendSignal(
            trend_type="risk_pattern",
            target_label=label,
            topic=sectors[0] if sectors else "global",
            intensity_score=final_score,
            window_start=start,
            window_end=end,
            description=description,
            metrics_json=metrics
        ))
        
    return patterns

async def _detect_entity_heat(recent: List[EventCluster], history: List[EventCluster], start: datetime, end: datetime) -> List[TrendSignal]:
    """Detects entities that are appearing more frequently than baseline."""
    signals = []
    baseline_entities = {}
    for c in history:
        entities = c.summary_data.get("top_entities", {})
        for ent, count in entities.items():
            baseline_entities[ent] = baseline_entities.get(ent, 0) + count
            
    recent_entities = {}
    for c in recent:
        entities = c.summary_data.get("top_entities", {})
        for ent, count in entities.items():
            recent_entities[ent] = recent_entities.get(ent, 0) + count
            
    # Calculate daily baseline avg
    recent_ts = recent[0].created_at if recent[0].created_at.tzinfo else recent[0].created_at.replace(tzinfo=timezone.utc)
    days = (recent_ts - start).days if recent and history else 7
    days = max(days, 1)
    
    for ent, count in recent_entities.items():
        baseline_avg = baseline_entities.get(ent, 0) / days
        delta = count / baseline_avg if baseline_avg > 0 else (count if count > 2 else 0)
        
        if delta >= SURGE_THRESHOLD or (baseline_avg == 0 and count >= 3):
            description = "Significant activity surge detected."
            metrics = {
                "baseline": round(baseline_avg, 2),
                "recent": count,
                "delta": round(delta, 2),
                "supporting_cluster_count": len([c for c in recent if ent in str(c.summary_data.get("top_entities", {}))])
            }
            signals.append((TrendSignal(
                trend_type="entity_heat",
                target_label=ent,
                topic="global",
                intensity_score=float(delta),
                window_start=start,
                window_end=end,
                description=description,
                metrics_json=metrics
            ), None)) # No single cluster_id for entity heat
    return signals

async def _detect_sector_surges(recent: List[EventCluster], history: List[EventCluster], start: datetime, end: datetime) -> List[TrendSignal]:
    """Detects sector-level signal intensity surges."""
    signals = []
    sectors = ["geopolitics", "cyber", "economy", "supply_chain", "defense", "energy"]
    
    for sector in sectors:
        recent_signals = [c.avg_signal_score for c in recent if c.category == sector]
        historical_signals = [c.avg_signal_score for c in history if c.category == sector]
        
        recent_avg = sum(recent_signals) / len(recent_signals) if recent_signals else 0
        historical_avg = sum(historical_signals) / len(historical_signals) if historical_signals else 0
        
        delta = recent_avg / historical_avg if historical_avg > 0 else (1.0 if recent_avg > 0 else 0)
        
        if delta >= 1.2 and recent_avg > 0.3: # 20% surge in intensity
            description = f"Sector '{sector}' is experiencing elevated risk signals."
            metrics = {
                "baseline": round(historical_avg, 2),
                "recent": round(recent_avg, 2),
                "delta": round(delta, 2),
                "supporting_cluster_count": len(recent_signals)
            }
            signals.append((TrendSignal(
                trend_type="sector_surge",
                target_label=sector,
                topic=sector,
                intensity_score=float(delta),
                window_start=start,
                window_end=end,
                description=description,
                metrics_json=metrics
            ), None))
    return signals

async def _detect_sustained_events(recent: List[EventCluster], history: List[EventCluster], start: datetime, end: datetime) -> List[TrendSignal]:
    """Links clusters that represent the same ongoing event over multiple days."""
    signals = []
    for rc in recent:
        for hc in history:
            # Event Lineage Logic
            # 1. Representative Title Similarity (Fuzzy/Substring)
            title_match = rc.representative_title.lower()[:30] == hc.representative_title.lower()[:30]
            
            # 2. Entity Overlap
            rc_ents = set(rc.summary_data.get("top_entities", {}).keys())
            hc_ents = set(hc.summary_data.get("top_entities", {}).keys())
            ent_overlap = len(rc_ents.intersection(hc_ents))
            
            # 3. Category & Risk Noun Match
            cat_match = rc.category == hc.category
            
            if (title_match and ent_overlap >= 1) or (ent_overlap >= 2 and cat_match):
                description = rc.representative_title
                metrics = {
                    "baseline": hc.avg_signal_score,
                    "recent": rc.avg_signal_score,
                    "delta": round(rc.avg_signal_score - hc.avg_signal_score, 2),
                    "supporting_cluster_count": rc.article_count + hc.article_count,
                    "cluster_id": str(rc.id)
                }
                signals.append((TrendSignal(
                    trend_type="sustained_event",
                    target_label=rc.representative_title[:50],
                    topic=rc.category or "global",
                    intensity_score=float(rc.avg_signal_score),
                    window_start=_ensure_utc(hc.created_at),
                    window_end=_ensure_utc(rc.created_at),
                    description=description,
                    metrics_json=metrics
                ), str(rc.id)))
                break # Move to next recent cluster
    return signals

async def _detect_risk_acceleration(recent: List[EventCluster], history: List[EventCluster], start: datetime, end: datetime) -> List[TrendSignal]:
    """Detects events where risk intensity is accelerating rapidly."""
    signals = []
    for rc in recent:
        if rc.avg_signal_score > 0.6: # High signal threshold
            # Check if this high-risk event is new or accelerating
            is_new = True
            for hc in history:
                if rc.representative_title.lower()[:20] == hc.representative_title.lower()[:20]:
                    is_new = False
                    if rc.avg_signal_score > hc.avg_signal_score * 1.5:
                        # Escalation detected
                        description = rc.representative_title
                        metrics = {
                            "baseline": hc.avg_signal_score,
                            "recent": rc.avg_signal_score,
                            "delta": round(rc.avg_signal_score / hc.avg_signal_score, 2) if hc.avg_signal_score > 0 else 2.0,
                            "supporting_cluster_count": rc.article_count,
                            "cluster_id": str(rc.id)
                        }
                        signals.append((TrendSignal(
                            trend_type="risk_acceleration",
                            target_label=rc.representative_title[:50],
                            topic=rc.category or "global",
                            intensity_score=float(rc.avg_signal_score),
                            window_start=_ensure_utc(hc.created_at),
                            window_end=_ensure_utc(rc.created_at),
                            description=description,
                            metrics_json=metrics
                        ), str(rc.id)))
                        is_new = False
                        break # Prevent duplicates
            
            if is_new and rc.avg_signal_score > 0.7:
                # High-risk NEW event is also a form of acceleration/surge
                description = rc.representative_title
                metrics = {
                    "baseline": 0.0,
                    "recent": rc.avg_signal_score,
                    "delta": rc.avg_signal_score,
                    "supporting_cluster_count": rc.article_count,
                    "cluster_id": str(rc.id)
                }
                signals.append((TrendSignal(
                    trend_type="risk_acceleration",
                    target_label=rc.representative_title[:50],
                    topic=rc.category or "global",
                    intensity_score=float(rc.avg_signal_score),
                    window_start=_ensure_utc(rc.created_at),
                    window_end=_ensure_utc(rc.created_at),
                    description=description,
                    metrics_json=metrics
                ), str(rc.id)))
    return signals
async def main():
    from db.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await detect_trends(session)
        await session.commit()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
