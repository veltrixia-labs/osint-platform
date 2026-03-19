import asyncio
import logging
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from db.database import AsyncSessionLocal
from db.models import Item, Topic, ItemTopic, AnalysisCache
from llm.client import generate_analysis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Constants & Config ---
MAX_TOP_K_TOTAL = 30
CATEGORY_QUOTA = 10
BATCH_SIZE = 10
CACHE_TTL_DAYS = 3
PROMPT_VERSION = "v2_batch_classify"

INITIAL_TOPICS = [
    {"code": "energy_resource_risk", "en": "Energy & Resource Risk", "keywords": ["oil", "crude", "OPEC", "LNG", "natural gas", "uranium", "mining", "energy"]},
    {"code": "global_market_intelligence", "en": "Global Market Intelligence", "keywords": ["fed", "interest rate", "inflation", "recession", "gdp", "stocks", "nasdaq", "bond", "yield"]},
    {"code": "crypto_geopolitics", "en": "Crypto & Regulatory Geopolitics", "keywords": ["bitcoin", "ethereum", "crypto", "blockchain", "defi", "stablecoin", "cbdc", "sec", "regulation"]},
    {"code": "ai_semiconductor_intelligence", "en": "AI & Semiconductor Intelligence", "keywords": ["ai", "nvidia", "tsmc", "intel", "semiconductor", "chip", "llm", "export control"]},
    {"code": "defense_technology", "en": "Defense & Security Technology", "keywords": ["war", "military", "missile", "drone", "defense", "nato", "sanction", "cyber", "espionage"]},
    {"code": "supply_chain_intelligence", "en": "Supply Chain Intelligence", "keywords": ["supply chain", "shipping", "freight", "logistics", "port", "trade", "tariff", "bottleneck"]},
]

async def seed_topics(db: AsyncSession):
    for t in INITIAL_TOPICS:
        stmt = select(Topic).where(Topic.topic_code == t["code"])
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if not existing:
            db.add(Topic(topic_code=t["code"], topic_name_en=t["en"]))
    await db.commit()

# --- Stage 1: Pre-processing & Lightweight Logic ---

def calculate_lightweight_score(item: Item, matched_kws: List[str]) -> float:
    score = 0.0
    # 1. Keywords density
    score += min(2.0, len(matched_kws) * 0.4)
    # 2. Source Authority (Institutional boost)
    if (item.source_group or "") in {"central_banks", "regulators", "policy_institutions"}:
        score += 1.5
    # 3. Recency (within 12h)
    now = datetime.now(timezone.utc)
    pub_at = item.published_at or item.created_at
    if pub_at.tzinfo is None: pub_at = pub_at.replace(tzinfo=timezone.utc)
    hours_old = (now - pub_at).total_seconds() / 3600
    if hours_old < 12: score += 1.0
    return score

async def pre_filter_and_score(db: AsyncSession, items: List[Item]) -> List[Item]:
    """Stage 1: Dedupe, Noise Filter, Rough Classification, Lightweight Scoring."""
    logger.info(f"[Stage 1] Pre-filtering {len(items)} items")
    filtered = []
    seen_titles = set()

    for item in items:
        # 1. Noise Filter
        if not item.title or len(item.title) < 10: continue
        if not item.summary or len(item.summary) < 20: continue
        
        # 2. Dedupe (Normalized Title)
        norm_title = "".join(filter(str.isalnum, item.title.lower()))
        if norm_title in seen_titles: continue
        seen_titles.add(norm_title)
        
        # 3. Rough Classification & Score
        text = f"{item.title} {item.summary}".lower()
        best_topic = None
        max_kws = 0
        all_matched = []
        
        for t in INITIAL_TOPICS:
            matched = [kw for kw in t["keywords"] if kw.lower() in text]
            if len(matched) > max_kws:
                max_kws = len(matched)
                best_topic = t["code"]
                all_matched = matched
        
        item.rough_category = best_topic or "misc"
        item.lightweight_score = calculate_lightweight_score(item, all_matched)
        filtered.append(item)
        
    return filtered

def select_top_k(items: List[Item]) -> List[Item]:
    """Top-K Selection with Category Quotas."""
    # Sort by score descending
    items.sort(key=lambda x: x.lightweight_score, reverse=True)
    
    selected = []
    cat_counts = {}
    
    for item in items:
        if len(selected) >= MAX_TOP_K_TOTAL: break
        
        cat = item.rough_category
        count = cat_counts.get(cat, 0)
        
        if count < CATEGORY_QUOTA or cat == "misc":
            selected.append(item)
            cat_counts[cat] = count + 1
            
    logger.info(f"Top-K selected {len(selected)} candidates for LLM analysis.")
    return selected

# --- Stage 2: Batch LLM Classification ---

async def batch_classify_llm(items: List[Item]) -> Dict[str, Dict]:
    """Calls LLM to classify items in batches."""
    results = {}
    
    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i+BATCH_SIZE]
        articles_json = []
        for it in batch:
            articles_json.append({
                "id": str(it.id),
                "title": it.title,
                "summary": it.summary[:300], # Truncate for tokens
                "source": it.source_name
            })
            
        system_prompt = (
            "You are an OSINT Risk Analyst. Classify the following articles into one of these categories: "
            f"{[t['code'] for t in INITIAL_TOPICS]}, or 'none'.\n"
            "Return a JSON object with 'results' as a list of objects, each containing:\n"
            "- article_id (exactly as provided)\n- category (code)\n- confidence (0-1)\n- keep (boolean, true if high impact/risk)\n- reason (short)\n"
            "Strictly JSON only."
        )
        user_prompt = f"Articles for classification:\n{json.dumps(articles_json, indent=2)}"
        
        logger.info(f"Sending batch of {len(batch)} to LLM...")
        batch_res = await generate_analysis(system_prompt, user_prompt, is_batch=True)
        
        if batch_res == "__DEGRADED_MODE__" or not isinstance(batch_res, dict):
            logger.warning("LLM Batch Classification failed. Using Degraded Mode fallback.")
            for it in batch:
                results[str(it.id)] = {"category": it.rough_category, "confidence": 0.5, "keep": it.lightweight_score > 2.0, "reason": "Degraded Mode (Lightweight)"}
        else:
            # Match results back by ID
            for res_item in batch_res.get("results", []):
                results[res_item["article_id"]] = res_item
                
    return results

async def run_classify(db: AsyncSession):
    logger.info("Starting High-Efficiency Classify Job")
    await seed_topics(db)
    
    # Reset counts for metrics
    metrics = {"fetched": 0, "pre_filtered": 0, "llm_analyzed": 0, "cache_hits": 0}
    
    # 1. Fetch unclassified or expired cache
    now = datetime.now(timezone.utc)
    stmt = select(Item).limit(100) # Process latest 100
    all_items = (await db.execute(stmt)).scalars().all()
    metrics["fetched"] = len(all_items)
    
    # 2. Stage 1: Pre-filter & Score
    pre_candidates = await pre_filter_and_score(db, all_items)
    metrics["pre_filtered"] = len(pre_candidates)
    
    # 3. Check Cache & Filter for Stage 2
    candidates_to_analyze = []
    for it in pre_candidates:
        cache_stmt = select(AnalysisCache).where(AnalysisCache.item_id == it.id)
        cache = (await db.execute(cache_stmt)).scalar_one_or_none()
        if cache:
            expires_at = cache.cache_expires_at
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            
            if expires_at and expires_at > now:
                metrics["cache_hits"] += 1
                it.category = cache.classification_result.get("category")
                continue
        
        candidates_to_analyze.append(it)
        
    # 4. Top-K Selection for remaining
    final_candidates = select_top_k(candidates_to_analyze)
    
    # 5. Stage 2: Batch LLM
    llm_results = await batch_classify_llm(final_candidates)
    metrics["llm_analyzed"] = len(llm_results)
    
    # 6. Apply Results & Save to Cache
    for it in final_candidates:
        res = llm_results.get(str(it.id))
        if res:
            it.category = res.get("category")
            # Update cache
            expires = now + timedelta(days=CACHE_TTL_DAYS)
            cache_stmt = select(AnalysisCache).where(AnalysisCache.item_id == it.id)
            cache = (await db.execute(cache_stmt)).scalar_one_or_none()
            if cache:
                cache.classification_result = res
                cache.cache_expires_at = expires
            else:
                db.add(AnalysisCache(
                    item_id=it.id,
                    model_name="batch_v1",
                    prompt_version=PROMPT_VERSION,
                    classification_result=res,
                    cache_expires_at=expires
                ))
            
            # Upsert ItemTopic for report compatibility
            if it.category and it.category != "none" and res.get("keep"):
                stmt_it = select(ItemTopic).where(ItemTopic.item_id == it.id, ItemTopic.topic_code == it.category)
                existing_it = (await db.execute(stmt_it)).scalar_one_or_none()
                if not existing_it:
                    db.add(ItemTopic(
                        item_id=it.id,
                        topic_code=it.category,
                        confidence_score=res.get("confidence", 0.5),
                        matched_keywords=[res.get("reason", "LLM Selection")]
                    ))

    await db.commit()
    logger.info(f"Classify finished. Metrics: {metrics}")

if __name__ == "__main__":
    async def main():
        async with AsyncSessionLocal() as session:
            await run_classify(session)
    asyncio.run(main())
